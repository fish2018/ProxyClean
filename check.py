import yaml
import httpx
import asyncio
from typing import Dict, List, Optional, Set
import sys
from datetime import datetime
from asyncio import Semaphore
import argparse

# 配置参数
TEST_URL = "http://www.gstatic.com/generate_204"
CLASH_API_PORTS = [9090, 9097]  # 支持多个端口
CLASH_API_HOST = "127.0.0.1"
CLASH_API_SECRET = ""
TIMEOUT = 5
MAX_CONCURRENT_TESTS = 100


class ClashAPIException(Exception):
    """自定义 Clash API 异常"""
    pass


class ProxyTestResult:
    """代理测试结果类"""

    def __init__(self, name: str, delay: Optional[float] = None):
        self.name = name
        self.delay = delay if delay is not None else float('inf')
        self.status = "ok" if delay is not None else "fail"
        self.tested_time = datetime.now()

    @property
    def is_valid(self) -> bool:
        return self.status == "ok"


class ClashAPI:
    def __init__(self, host: str, ports: List[int], secret: str = ""):
        self.host = host
        self.ports = ports
        self.base_url = None  # 将在连接检查时设置
        self.headers = {
            "Authorization": f"Bearer {secret}" if secret else "",
            "Content-Type": "application/json"
        }
        self.client = httpx.AsyncClient(timeout=TIMEOUT)
        self.semaphore = Semaphore(MAX_CONCURRENT_TESTS)
        self._test_results_cache: Dict[str, ProxyTestResult] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def check_connection(self) -> bool:
        """检查与 Clash API 的连接状态，自动尝试不同端口"""
        for port in self.ports:
            try:
                test_url = f"http://{self.host}:{port}"
                response = await self.client.get(f"{test_url}/version")
                if response.status_code == 200:
                    version = response.json().get('version', 'unknown')
                    print(f"成功连接到 Clash API (端口 {port})，版本: {version}")
                    self.base_url = test_url
                    return True
            except httpx.RequestError:
                print(f"端口 {port} 连接失败，尝试下一个端口...")
                continue

        print("所有端口均连接失败")
        print(f"请确保 Clash 正在运行，并且 External Controller 已启用于以下端口之一: {', '.join(map(str, self.ports))}")
        return False

    async def get_proxies(self) -> Dict:
        """获取所有代理节点信息"""
        if not self.base_url:
            raise ClashAPIException("未建立与 Clash API 的连接")

        try:
            response = await self.client.get(
                f"{self.base_url}/proxies",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                print("认证失败，请检查 API Secret 是否正确")
            raise ClashAPIException(f"HTTP 错误: {e}")
        except httpx.RequestError as e:
            raise ClashAPIException(f"请求错误: {e}")

    async def test_proxy_delay(self, proxy_name: str) -> ProxyTestResult:
        """测试指定代理节点的延迟，使用缓存避免重复测试"""
        if not self.base_url:
            raise ClashAPIException("未建立与 Clash API 的连接")

        # 检查缓存
        if proxy_name in self._test_results_cache:
            cached_result = self._test_results_cache[proxy_name]
            # 如果测试结果不超过60秒，直接返回缓存的结果
            if (datetime.now() - cached_result.tested_time).total_seconds() < 60:
                return cached_result

        async with self.semaphore:
            try:
                response = await self.client.get(
                    f"{self.base_url}/proxies/{proxy_name}/delay",
                    headers=self.headers,
                    params={"url": TEST_URL, "timeout": TIMEOUT * 1000}
                )
                response.raise_for_status()
                delay = response.json().get("delay")
                result = ProxyTestResult(proxy_name, delay)
            except httpx.HTTPError:
                result = ProxyTestResult(proxy_name)

            # 更新缓存
            self._test_results_cache[proxy_name] = result
            return result


class ClashConfig:
    """Clash 配置管理类"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()
        self.proxy_groups = self._get_proxy_groups()

    def _load_config(self) -> dict:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"找不到配置文件: {self.config_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"配置文件格式错误: {e}")
            sys.exit(1)

    def _get_proxy_groups(self) -> List[Dict]:
        """获取所有代理组信息"""
        return self.config.get("proxy-groups", [])

    def get_group_names(self) -> List[str]:
        """获取所有代理组名称"""
        return [group["name"] for group in self.proxy_groups]

    def get_group_proxies(self, group_name: str) -> List[str]:
        """获取指定组的所有代理"""
        for group in self.proxy_groups:
            if group["name"] == group_name:
                return group.get("proxies", [])
        return []

    def remove_invalid_proxies(self, results: List[ProxyTestResult]):
        """从配置中完全移除失效的节点"""
        # 获取所有失效节点名称
        invalid_proxies = {r.name for r in results if not r.is_valid}

        if not invalid_proxies:
            return

        # 从 proxies 部分移除失效节点
        valid_proxies = []
        if "proxies" in self.config:
            valid_proxies = [p for p in self.config["proxies"]
                             if p.get("name") not in invalid_proxies]
            self.config["proxies"] = valid_proxies

        # 从所有代理组中移除失效节点
        for group in self.proxy_groups:
            if "proxies" in group:
                group["proxies"] = [p for p in group["proxies"]
                                    if p not in invalid_proxies]

        print(f"\n已从配置中移除 {len(invalid_proxies)} 个失效节点")

    def update_group_proxies(self, group_name: str, results: List[ProxyTestResult]):
        """更新指定组的代理列表，仅保留有效节点并按延迟排序"""
        # 移除失效节点
        self.remove_invalid_proxies(results)

        # 获取有效节点并按延迟排序
        valid_results = [r for r in results if r.is_valid]
        valid_results = list(set(valid_results))
        valid_results.sort(key=lambda x: x.delay)

        # 更新代理组
        for group in self.proxy_groups:
            if group["name"] == group_name:
                group["proxies"] = [r.name for r in valid_results]
                break

    def save(self):
        """保存配置到文件"""
        try:
            # 保存新配置
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, allow_unicode=True, sort_keys=False)
            print(f"新配置已保存到: {self.config_path}")
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            sys.exit(1)


def print_test_summary(group_name: str, results: List[ProxyTestResult]):
    """打印测试结果摘要"""
    valid_results = [r for r in results if r.is_valid]
    invalid_results = [r for r in results if not r.is_valid]
    total = len(results)
    valid = len(valid_results)
    invalid = len(invalid_results)

    print(f"\n策略组 '{group_name}' 测试结果:")
    print(f"总节点数: {total}")
    print(f"可用节点数: {valid}")
    print(f"失效节点数: {invalid}")

    if valid > 0:
        avg_delay = sum(r.delay for r in valid_results) / valid
        print(f"平均延迟: {avg_delay:.2f}ms")

        print("\n延迟最低的前5个节点:")
        sorted_results = sorted(valid_results, key=lambda x: x.delay)
        for i, result in enumerate(sorted_results[:5], 1):
            print(f"{i}. {result.name}: {result.delay:.2f}ms")

    if invalid > 0:
        print("\n失效节点:")
        for i, result in enumerate(invalid_results, 1):
            print(f"{i}. {result.name}")


async def test_group_proxies(clash_api: ClashAPI, proxies: List[str]) -> List[ProxyTestResult]:
    """测试一组代理节点"""
    print(f"开始测试 {len(proxies)} 个节点 (最大并发: {MAX_CONCURRENT_TESTS})")

    # 创建所有测试任务
    tasks = [clash_api.test_proxy_delay(proxy_name) for proxy_name in proxies]

    # 使用进度显示执行所有任务
    results = []
    for future in asyncio.as_completed(tasks):
        result = await future
        results.append(result)
        # 显示进度
        done = len(results)
        total = len(tasks)
        print(f"\r进度: {done}/{total} ({done / total * 100:.1f}%)", end="", flush=True)

    print("\n")  # 换行
    return results


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='Clash 代理节点测试和清理工具')
    parser.add_argument('-c', '--config', default='clash_config.yaml',
                        help='Clash 配置文件路径 (默认: clash_config.yaml)')
    parser.add_argument('-g', '--groups', nargs='*',
                        help='要测试的策略组名称 (默认: 测试所有组)')
    parser.add_argument('-n', '--concurrent', type=int, default=MAX_CONCURRENT_TESTS,
                        help=f'最大并发测试数量 (默认: {MAX_CONCURRENT_TESTS})')
    parser.add_argument('-t', '--timeout', type=int, default=TIMEOUT,
                        help=f'测试超时时间（秒）(默认: {TIMEOUT})')
    parser.add_argument('-p', '--ports', type=int, nargs='*', default=CLASH_API_PORTS,
                        help=f'Clash API 端口列表 (默认: {" ".join(map(str, CLASH_API_PORTS))})')
    parser.add_argument('-s', '--secret',
                        help='Clash API Secret')
    return parser.parse_args()


async def main():
    args = parse_arguments()

    # 更新全局配置
    global MAX_CONCURRENT_TESTS, TIMEOUT, CLASH_API_SECRET
    MAX_CONCURRENT_TESTS = args.concurrent
    TIMEOUT = args.timeout
    CLASH_API_SECRET = args.secret or CLASH_API_SECRET

    print(f"Clash 节点测试和清理工具")
    print(f"配置文件: {args.config}")
    print(f"API 端口: {args.ports}")
    print(f"并发数量: {MAX_CONCURRENT_TESTS}")
    print(f"超时时间: {TIMEOUT}秒")

    # 加载配置
    config = ClashConfig(args.config)
    available_groups = config.get_group_names()

    # 确定要测试的策略组
    groups_to_test = args.groups if args.groups else available_groups
    invalid_groups = set(groups_to_test) - set(available_groups)
    if invalid_groups:
        print(f"警告: 以下策略组不存在: {', '.join(invalid_groups)}")
        groups_to_test = list(set(groups_to_test) & set(available_groups))

    if not groups_to_test:
        print("错误: 没有找到要测试的有效策略组")
        print(f"可用的策略组: {', '.join(available_groups)}")
        return

    print(f"\n将测试以下策略组: {', '.join(groups_to_test)}")

    # 开始测试
    start_time = datetime.now()

    # 创建支持多端口的API实例
    async with ClashAPI(CLASH_API_HOST, args.ports, CLASH_API_SECRET) as clash_api:
        if not await clash_api.check_connection():
            return

        try:
            all_test_results = []  # 收集所有测试结果

            # 测试每个策略组
            for group_name in groups_to_test:
                print(f"\n======================== 开始测试策略组: {group_name} ====================")
                proxies = config.get_group_proxies(group_name)

                if not proxies:
                    print(f"策略组 '{group_name}' 中没有代理节点")
                    continue

                # 测试该组的所有节点
                results = await test_group_proxies(clash_api, proxies)
                all_test_results.extend(results)

                # 打印测试结果摘要
                print_test_summary(group_name, results)

            # 一次性移除所有失效节点并更新配置
            config.remove_invalid_proxies(all_test_results)

            # 为每个组更新有效节点的顺序
            for group_name in groups_to_test:
                group_proxies = config.get_group_proxies(group_name)
                group_results = [r for r in all_test_results if r.name in group_proxies]
                config.update_group_proxies(group_name, group_results)
                print(f"已更新策略组 '{group_name}' 的节点顺序")

            # 保存更新后的配置
            config.save()

            # 显示总耗时
            total_time = (datetime.now() - start_time).total_seconds()
            print(f"\n总耗时: {total_time:.2f} 秒")

        except ClashAPIException as e:
            print(f"Clash API 错误: {e}")
        except Exception as e:
            print(f"发生错误: {e}")
            raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断执行")
        sys.exit(0)
    except Exception as e:
        print(f"程序执行失败: {e}")
        sys.exit(1)
