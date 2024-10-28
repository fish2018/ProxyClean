### clash_yaml_check
批量检测节点有效性，自动剔除失效节点，并根据延迟自动排序  
可以测试指定的策略组  
可以测试所有策略组  
独立显示每个组的测试结果  
添加了测试结果缓存: 
相同节点在60秒内不会重复测试  
提高了多策略组测试的效率  

### 联通性测试url
| 服务提供者 | 链接 | 大陆体验 | 境外体验 | http/https | IP Version |
|------------|------|----------|----------|-----------|------------|
| Google     | http://www.gstatic.com/generate_204 | 5 | 10 | 204/204 | 4+6 |
| Google     | http://www.google-analytics.com/generate_204 | 6 | 10 | 204/204 | 4+6 |
| Google     | http://www.google.com/generate_204 | 0 | 10 | 204/204 | 4+6 |
| Google     | http://connectivitycheck.gstatic.com/generate_204 | 4 | 10 | 204/204 | 4+6 |
| Apple      | http://captive.apple.com | 3 | 10 | 200/200 | 4+6 |
| Apple🔥    | http://www.apple.com/library/test/success.html | 7 | 10 | 200/200 | 4+6 |
| MicroSoft  | http://www.msftconnecttest.com/connecttest.txt | 5 | 10 | 200/error | 4 |
| Cloudflare  | http://cp.cloudflare.com/ | 4 | 10 | 204/204 | 4+6 |
| Firefox    | http://detectportal.firefox.com/success.txt | 5 | 10 | 200/200 | 4+6 |
| V2ex       | http://www.v2ex.com/generate_204 | 0 | 10 | 204/301 | 4+6 |
| 小米       | http://connect.rom.miui.com/generate_204 | 10 | 4 | 204/204 | 4 |
| 华为       | http://connectivitycheck.platform.hicloud.com/generate_204 | 10 | 5 | 204/204 | 4 |
| Vivo       | http://wifi.vivo.com.cn/generate_204 | 10 | 5 | 204/204 | 4 |

### 使用说明  
添加了命令行参数支持:  
- -c/--config: 指定配置文件路径，默认config.yaml
- -g/--groups: 指定要测试的策略组
- -n/--concurrent: 设置并发数
- -t/--timeout: 设置超时时间
- -u/--url: 设置 API 地址
- -s/--secret: 设置 API secret

使用示例:

测试所有策略组:
```
python check.py
```
测试指定策略组:
```
python check.py -g "自动选择"
```

### CLASH API默认端口说明
1. Clash 核心
- Clash Premium: 9090 (遵循配置文件中的external-controller设置)
- Clash Core: 9090 (遵循配置文件设置)

2. Windows 客户端
- Clash for Windows: 9090
- Clash Verge: 9097
- ClashN: 9090
- Fndroid: 9090

3. macOS 客户端
- ClashX: 9090
- ClashX Pro: 9090
- Clash Verge: 9097

4. Linux 客户端
- Clash Verge: 9097
- Clash for Windows: 9090

5. Android 客户端
- ClashForAndroid: 9090
