# _*_ coding: utf-8 _*_
import copy
import traceback
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote_plus

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.helper.sites import SitesHelper

from app.core.context import TorrentInfo
from app.plugins import _PluginBase
from app.core.config import settings
from app.schemas import MediaType
from app.utils.http import RequestUtils
from app.log import logger
from app.utils.string import StringUtils


class ProwlarrExtend(_PluginBase):
    # 插件名称
    plugin_name = "ProwlarrExtend"
    # 插件描述
    plugin_desc = "扩展检索以支持Prowlarr站点资源"
    # 插件图标
    plugin_icon = "Prowlarr.png"
    # 插件版本
    plugin_version = "1.2"
    # 插件作者
    plugin_author = "jtcymc"
    # 作者主页
    author_url = "https://github.com/jtcymc"
    # 插件配置项ID前缀
    plugin_config_prefix = "prowlarr_extend_"
    # 加载顺序
    plugin_order = 16
    # 可使用的用户级别
    auth_level = 1
    # 私有属性
    _scheduler = None
    _cron = None
    _enabled = False
    _proxy = False
    _host = ""
    _api_key = ""
    _onlyonce = False
    _indexers = []
    sites_helper = None
    # 仅用于标识，避免重复注册
    prowlarr_domain = "prowlarr_extend.jtcymc"

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        self.sites_helper = SitesHelper()
        # 读取配置
        if config:
            self._host = config.get("host")
            if self._host:
                if not self._host.startswith('http'):
                    self._host = "http://" + self._host
                if self._host.endswith('/'):
                    self._host = self._host.rstrip('/')
            self._api_key = config.get("api_key")
            self._enabled = config.get("enabled")
            self._proxy = config.get("proxy")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron") or "0 0 */24 * *"

        # 停止现有任务
        self.stop_service()
        # 启动定时任务 & 立即运行一次
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        if self._cron:
            logger.info(f"【{self.plugin_name}】 索引更新服务启动，周期：{self._cron}")
            self._scheduler.add_job(self.get_status, CronTrigger.from_crontab(self._cron))

        if self._onlyonce:
            logger.info(f"【{self.plugin_name}】开始获取索引器状态")
            self._scheduler.add_job(self.get_status, 'date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3))
            # 关闭一次性开关
            self._onlyonce = False
            self.__update_config()

        if self._cron or self._onlyonce:
            # 启动服务
            self._scheduler.print_jobs()
            self._scheduler.start()
        if not self._indexers:
            self.get_status()
        for indexer in self._indexers:
            domain = indexer.get("domain", "")
            site_info = self.sites_helper.get_indexer(domain)
            if not site_info:
                new_indexer = copy.deepcopy(indexer)
                # sites_helper 添加prowlarr_indexer
                self.sites_helper.add_indexer(domain, new_indexer)

    def get_status(self):
        """
        检查连通性
        :return: True、False
        """
        if not self._api_key or not self._host:
            return False
        self._indexers = self.get_indexers()
        return True if isinstance(self._indexers, list) and len(self._indexers) > 0 else False

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"【{self.plugin_name}】停止插件错误: {str(e)}")

    def __update_config(self):
        """
        更新插件配置
        """
        self.update_config({
            "onlyonce": False,
            "cron": self._cron,
            "host": self._host,
            "api_key": self._api_key
        })

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        pass

    def get_module(self) -> Dict[str, Any]:
        """
        获取插件模块声明，用于胁持系统模块实现（方法名：方法实现）
        {
            "id1": self.xxx1,
            "id2": self.xxx2,
        }
        """
        return {
            "search_torrents": self.search_torrents,
        }

    def get_indexers(self):
        """
        获取配置的 Prowlarr Indexer 信息

        :return: Indexer 列表，包含 id, name, url, domain, public, proxy 信息
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }
        indexer_query_url = f"{self._host.rstrip('/')}/api/v1/indexerstats"
        try:
            ret = RequestUtils(headers=headers).get_res(indexer_query_url)
            if not ret:
                logger.warning(f"【{self.plugin_name}】获取 indexer 请求无响应")
                return []

            data = ret.json()
            if not data or "indexers" not in data:
                logger.warning(f"【{self.plugin_name}】返回数据不包含 indexers 字段")
                return []

            indexers_raw = data.get("indexers", [])
            if not indexers_raw:
                logger.info(f"【{self.plugin_name}】未配置任何 indexer")
                return []

            indexers = []
            for v in indexers_raw:
                indexer_id = v.get("indexerId")
                indexer_name = v.get("indexerName")
                if not indexer_id or not indexer_name:
                    continue

                indexers.append({
                    "id": f'{self.plugin_name}-{indexer_name}',
                    "name": f'{self.plugin_name}-{indexer_name}',
                    "url": f'{self._host.rstrip("/")}/api/v1/indexer/{indexer_id}',
                    "domain": self.prowlarr_domain.replace(self.plugin_author, str(indexer_id)),
                    "public": True,
                    "proxy": False,
                })

            return indexers
        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取 indexer 失败：{str(e)}")
            return []

    def search_torrents(self, site, keywords, mtype: Optional[MediaType] = None, page: Optional[int] = 0) -> List[
        TorrentInfo]:
        """
        根据关键字检索种子
        """
        results = []

        if not site or not keywords:
            return results

        if site.get("name", "").split("-")[0] != self.plugin_name:
            return results

        # 提取 Indexer ID
        domain = StringUtils.get_url_domain(site.get("domain", ""))
        indexer_id = domain.split(".")[-1] if domain else ""
        if not indexer_id:
            logger.warning(f"【{self.plugin_name}】无法提取索引 ID，跳过站点：{site.get('name')}")
            return results

        # 构建请求头
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }
        categories = self.get_cat(mtype)
        for keyword in keywords:
            if not keyword:
                continue
            try:
                logger.info(f"【{self.plugin_name}】开始检索 Indexer：{site.get('name')}，关键词：{keyword}")
                params = [
                             ("query", keyword),
                             ("indexerIds", indexer_id),
                             ("type", "search"),
                             ("limit", 150),
                             ("offset", page * 150 if page else 0),
                         ] + [("categories", cat) for cat in categories]
                query_string = urlencode(params, quote_via=quote_plus)
                api_url = f"{self._host.rstrip('/')}/api/v1/search?{query_string}"

                response = RequestUtils(headers=headers).get_res(api_url)
                if not response:
                    logger.warning(f"【{self.plugin_name}】{site.get('name')} 返回为空")
                    continue

                data = response.json()
                if not isinstance(data, list):
                    logger.warning(f"【{self.plugin_name}】{site.get('name')} 返回数据格式异常")
                    continue

                for entry in data:
                    torrent = TorrentInfo(
                        title=entry.get("title"),
                        enclosure=entry.get("downloadUrl") or entry.get("magnetUrl"),
                        description=entry.get("sortTitle"),
                        size=entry.get("size"),
                        seeders=entry.get("seeders"),
                        pubdate=entry.get("publishDate"),
                        page_url=entry.get("infoUrl") or entry.get("guid"),
                    )
                    results.append(torrent)

            except Exception as e:
                logger.error(f"【{self.plugin_name}】检索错误：{str(e)}\n{traceback.format_exc()}")

        return results

    @staticmethod
    def get_cat(mtype: Optional[MediaType] = None):
        if not mtype:
            return [2000, 5000]
        elif mtype == MediaType.MOVIE:
            return [2000]
        elif mtype == MediaType.TV:
            return [5000]
        else:
            return [2000, 5000]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'proxy',
                                            'label': '使用代理服务器',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                            'hint': '打开后立即运行一次获取索引器列表，否则需要等到预先设置的更新周期才会获取'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '更新周期',
                                            'placeholder': '0 0 */24 * *',
                                            'hint': '索引列表更新周期，支持5位cron表达式，默认每24小时运行一次'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'host',
                                            'label': 'Prowlarr地址',
                                            'placeholder': 'http://127.0.0.1:9696',
                                            'hint': 'Prowlarr访问地址和端口，如为https需加https://前缀。注意需要先在Prowlarr中添加搜刮器，同时勾选所有搜刮器后搜索一次，才能正常测试通过和使用'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'api_key',
                                            'label': 'Api Key',
                                            'placeholder': '',
                                            'hint': '在Prowlarr->Settings->General->Security-> API Key中获取'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'success',
                                            'variant': 'tonal',
                                            'text': '将“查看数据”列表中 “站点domain” => 站点管理 新增站点 站点名+ https://或http:// 直接新增'}
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '该种方式扩建检索，无法进行站点连通性监测，官方默认方式添加的正常不影响！'
                                                    '日志出现报如下错误时，可以不用管，由于插件没有检索到数据会触发后续模块检索，导致错误'
                                                    'indexer - 【ProwlarrExtend】ACG.RIP 搜索出错：NoneType object has no attribute get'
                                        }
                                    }
                                ]
                            }
                        ]
                    }

                ]
            }
        ], {
            "host": "",
            "api_key": "",
            "cron": "0 0 */24 * *",
            "onlyonce": False
        }

    def _ensure_sites_loaded(self) -> bool:
        """
        确保 self._indexers 已加载数据，若为空则尝试重新加载。
        :return: 成功加载返回 True，否则 False
        """
        if isinstance(self._indexers, list) and len(self._indexers) > 0:
            return True

        # 尝试重新加载站点数据
        self.get_status()

        return isinstance(self._indexers, list) and len(self._indexers) > 0

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        if not self._ensure_sites_loaded():
            return []

        items = []
        for site in self._indexers:
            items.append({
                'component': 'tr',
                'content': [
                    {
                        'component': 'td',
                        'text': site.get("name")
                    },
                    {
                        'component': 'td',
                        'text': f"https://{site.get('domain')}"
                    },
                    {
                        'component': 'td',
                        'text': site.get("public")
                    }
                ]
            })

        return [
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12
                        },
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {
                                    'hover': True
                                },
                                'content': [
                                    {
                                        'component': 'thead',
                                        'content': [
                                            {
                                                'component': 'tr',
                                                'content': [
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': 'id'
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': '站点名称'
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': '是否公开'
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': items
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
