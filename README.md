# MoviePilot 插件

> **免责声明**  
> 本项目及其插件仅供学习与交流使用，严禁用于任何商业或非法用途。请遵守当地法律法规，因使用本项目产生的任何后果由使用者自行承担。

## 使用说明
1. 基础参数配置完成点击“保存”，再次点击插件“查看数据”
2. 复制站点=>MP站点管理=>添加站点=>粘贴到“站点地址”=>保存
![](https://raw.githubusercontent.com/jtcymc/MoviePilot-PluginsV2/main/docs/imgs/plugins_domains.png)
![](https://raw.githubusercontent.com/jtcymc/MoviePilot-PluginsV2/main/docs/imgs/add_site.png)
![](https://raw.githubusercontent.com/jtcymc/MoviePilot-PluginsV2/main/docs/imgs/plugin_site.png)
## 插件目录

### V2 版本插件

#### JackettExtend
- **插件名称**: JackettExtend
- **插件描述**: 扩展检索以支持 Jackett 站点资源
- **插件版本**: 1.0
- **插件作者**: jtcymc
- **作者主页**: https://github.com/jtcymc
- **主要功能**:
  - 支持配置 Jackett 服务器信息（地址、API Key、密码、代理等）
  - 定时获取 Jackett 索引器列表
  - 支持通过 Web 界面配置插件参数
  - 支持关键字资源搜索
  - 支持定时任务与手动触发索引器状态获取
  - 支持多站点资源聚合检索
- **使用方法**:
  1. 在插件配置页面填写 Jackett 服务器地址、API Key、密码（如有）、代理等信息
  2. 设置定时任务周期，或点击“立即运行一次”手动获取索引器列表
  3. 插件会自动定时更新索引器列表
  4. 可在详情页面查看已获取的索引器列表及状态
- **注意事项**:
  - 需先在 Jackett 中添加并配置好 indexer
  - 建议先在 Jackett 后台测试通过后再在本插件中使用

#### ProwlarrExtend
- **插件名称**: ProwlarrExtend
- **插件描述**: 扩展检索以支持 Prowlarr 站点资源
- **插件版本**: 1.0
- **插件作者**: jtcymc
- **作者主页**: https://github.com/jtcymc
- **主要功能**:
  - 支持配置 Prowlarr 服务器信息（地址、API Key、代理等）
  - 定时获取 Prowlarr 索引器列表
  - 支持通过 Web 界面配置插件参数
  - 支持关键字资源搜索
  - 支持定时任务与手动触发索引器状态获取
  - 支持多站点资源聚合检索
- **使用方法**:
  1. 在插件配置页面填写 Prowlarr 服务器地址、API Key、代理等信息
  2. 设置定时任务周期，或点击“立即运行一次”手动获取索引器列表
  3. 插件会自动定时更新索引器列表
  4. 可在详情页面查看已获取的索引器列表及状态
- **注意事项**:
  - 需先在 Prowlarr 中添加并配置好 indexer
  - 建议先在 Prowlarr 后台测试通过后再在本插件中使用

---

如需扩展更多 BT 站点或自定义插件，请参考 `plugins.v2` 目录下的插件实现方式。

---

如需进一步完善或有特殊格式需求，请告知！
