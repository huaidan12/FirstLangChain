# RedBook 标题生成服务（阿里云 FC + Coze 插件）

小红书爆款标题生成 API。部署到阿里云函数计算 FC 3.0，供 Coze 平台作为自定义插件调用。

## 目录结构

```
redBook/
├── main.py              FastAPI 应用（含 API Key 鉴权、Redis 计数）
├── bootstrap            FC Custom Runtime 启动脚本
├── requirements.txt     Python 依赖
├── s.yaml               Serverless Devs 部署描述
├── .fcignore            部署时排除的文件
└── README.md
```

## 一、准备工作

### 1.1 阿里云资源

- **函数计算 FC 3.0** 服务已开通
- **云数据库 Redis**：至少一个 1G 版即可（约 ¥30/月），记下**内网连接地址**和密码
- **专有网络 VPC**：Redis 所在的 VPC ID、交换机 ID、安全组 ID（FC 要挂到这个 VPC 才能连内网 Redis）
- **DashScope / DeepSeek API Key**：模型调用凭证

### 1.2 本地工具

```bash
npm install -g @serverless-devs/s
s config add          # 配置阿里云 AccessKey，命名为 default
```

## 二、部署

### 2.1 配置环境变量

```bash
export LLM_API_KEY="sk-xxx"
export REDIS_HOST="r-xxx.redis.rds.aliyuncs.com"
export REDIS_PASSWORD="xxx"
export API_KEYS="key1,key2"           # 逗号分隔，随便生成即可，Coze 侧要用其中一个
export VPC_ID="vpc-xxx"
export VSWITCH_ID="vsw-xxx"
export SECURITY_GROUP_ID="sg-xxx"
```

### 2.2 一键部署

```bash
cd projects/redBook
s deploy
```

部署完成后终端会打印函数的公网访问 URL，形如：

```
https://redbook-titles-xxx.cn-hangzhou.fcapp.run
```

### 2.3 验证

```bash
curl https://<你的URL>/health
# {"status":"ok"}

curl -X POST https://<你的URL>/generate/title \
  -H "Content-Type: application/json" \
  -H "X-API-Key: key1" \
  -d '{"user_id":"test","topic":"周末露营"}'
```

## 三、接入 Coze

1. Coze 开发者后台 → 插件 → **创建插件**
2. 插件类型选 **基于已有服务创建**
3. 插件 URL 填 FC 触发器 URL
4. 授权方式选 **Service**，Location = `Header`，Parameter name = `X-API-Key`，Service token = 你 `API_KEYS` 中的一个
5. 添加工具 `generate_title`：
   - 请求方法：POST
   - 路径：`/generate/title`
   - 输入参数：`user_id`（string）、`topic`（string）
   - 输出参数：`code`、`data`、`remaining_count`
6. 保存 → 调试通过 → 发布

Bot 编排时直接选 `generate_title` 工具即可使用。

## 四、常见坑

| 现象 | 原因 & 排查 |
|---|---|
| 冷启动首次请求 3-5s | FC 冷启动 + 装依赖，属正常。若无法容忍，开启 **预留实例** |
| 502 / Redis 连不上 | VPC/交换机/安全组三件套没配对，或安全组没放行 Redis 6379 端口 |
| LLM 401 | `LLM_API_KEY` 未生效，或 `LLM_MODEL` 与 `LLM_API_BASE` 不匹配（DashScope 兼容模式要用 `deepseek-v3` 类的模型名） |
| Coze 调用 401 | Coze 侧 `X-API-Key` 未配置或与 `API_KEYS` 不一致 |
| Coze 调用 403 | 用户已用完当日额度，属预期。调整 `DAILY_LIMIT` |

## 五、成本估算（月）

按小规模个人插件（约 1 万次调用/月）：

- FC 计算：几乎 0（免费额度内）
- Redis 1G 版：约 ¥30
- LLM 调用：视模型而定，DeepSeek 极便宜（¥1-5）

合计 **~ ¥35/月**。
