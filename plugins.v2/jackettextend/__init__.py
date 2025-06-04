# _*_ coding: utf-8 _*_
import copy
import traceback
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta
import xml.dom.minidom
from urllib.parse import urlencode, quote_plus

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.helper.sites import SitesHelper

from app.core.context import TorrentInfo
from app.log import logger
from app.plugins import _PluginBase
from app.core.config import settings
from app.schemas import MediaType
from app.utils.dom import DomUtils
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class JackettExtend(_PluginBase):
    # 插件名称
    plugin_name = "JackettExtend"
    # 插件描述
    plugin_desc = "扩展检索以支持Jackett站点资源"
    # 插件图标
    plugin_icon = "Jackett_A.png"
    # 插件版本
    plugin_version = "1.2"
    # 插件作者
    plugin_author = "jtcymc"
    # 作者主页
    author_url = "https://github.com/jtcymc"
    # 插件配置项ID前缀
    plugin_config_prefix = "jackett_extend_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _scheduler = None
    _cron = None
    _enabled = False
    _proxy = False
    _host = ""
    _api_key = ""
    _password = ""
    _onlyonce = False
    _indexers = []
    sites_helper = None
    # 仅用于标识，避免重复注册
    jackett_domain = "jackett_extend.jtcymc"

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
            self._password = config.get("password")
            self._enabled = config.get("enabled")
            self._proxy = config.get("proxy")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron") or "0 0 */24 * *"
        if not self._enabled:
            return
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
                # sites_helper 添加
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
            "api_key": self._api_key,
            "password": self._password,
        })

    def search_torrents(self, site, keywords, mtype: Optional[MediaType] = None, page: Optional[int] = 0) -> List[
        TorrentInfo]:
        """
        使用 Jackett Torznab API 根据关键字检索种子
        """
        results = []

        if not site or (site.get("name", "").split("-")[0] != self.plugin_name):
            return results

        domain = StringUtils.get_url_domain(site.get("domain", ""))
        if not domain:
            logger.warning(f"【{self.plugin_name}】站点域名无法解析")
            return results

        indexer_name = domain.split(".")[-1]
        categories = self.get_cat(mtype)

        for keyword in keywords:
            if not keyword:
                continue

            try:
                logger.info(f"【{self.plugin_name}】开始检索 Indexer：\"{site.get('name')}\"，关键词：\"{keyword}\"")

                params = {
                    "apikey": self._api_key,
                    "t": "search",
                    "q": keyword,
                    "cat": ",".join(map(str, categories))
                }
                query_string = urlencode(params, quote_via=quote_plus)
                api_url = f"{self._host.rstrip('/')}/api/v2.0/indexers/{indexer_name}/results/torznab/?{query_string}"

                result_array = self.__parse_torznab_xml(api_url)

                if not result_array:
                    logger.warning(f"【{self.plugin_name}】Indexer：\"{site.get('name')}\" 未检索到数据")
                    continue

                logger.info(f"【{self.plugin_name}】Indexer：\"{site.get('name')}\" 返回数据：{len(result_array)} 条")
                results.extend(result_array)

            except Exception as e:
                logger.error(f"【{self.plugin_name}】检索出错：{str(e)}")

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

    def get_indexers(self):
        """
        获取配置的 Jackett Indexer 信息
        :return: Indexer 列表，每项包含 id、name、url、domain、public、proxy、parser
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": settings.USER_AGENT,
            "X-Api-Key": self._api_key,
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }

        cookie = None
        session = requests.session()

        try:
            login_url = f"{self._host.rstrip('/')}/UI/Dashboard"
            login_data = {"password": self._password}
            login_params = {"password": self._password}
            login_res = RequestUtils(headers=headers, session=session).post_res(
                url=login_url,
                data=login_data,
                params=login_params,
                proxies=settings.PROXY if self._proxy else None
            )
            if login_res and session.cookies:
                cookie = session.cookies.get_dict()
            else:
                logger.warning(f"【{self.plugin_name}】Jackett 登录失败，无法获取 cookie")

            indexer_query_url = f"{self._host.rstrip('/')}/api/v2.0/indexers?configured=true"
            ret = RequestUtils(headers=headers, cookies=cookie).get_res(
                indexer_query_url,
                proxies=settings.PROXY if self._proxy else None
            )

            if not ret or not ret.json():
                logger.warning(f"【{self.plugin_name}】未获取到任何 indexer 配置")
                return []

            raw_indexers = ret.json()
            indexers = []
            for v in raw_indexers:
                indexer_id = v.get("id")
                indexer_name = v.get("name")
                if not indexer_id or not indexer_name:
                    continue

                indexers.append({
                    "id": f'{self.plugin_name}-{indexer_name}',
                    "name": f'{self.plugin_name}-{indexer_name}',
                    "url": f'{self._host.rstrip("/")}/api/v2.0/indexers/{indexer_id}/results/torznab/',
                    "domain": self.jackett_domain.replace(self.plugin_author, str(indexer_id)),
                    "public": True,
                    "proxy": False,
                })

            return indexers

        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取 Jackett indexers 失败：{str(e)}")
            return []

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

    def __parse_torznab_xml(self, url) -> List[TorrentInfo]:
        """
        从 torznab XML 中解析种子信息
        :param url: XML 数据的 URL
        :return: TorrentInfo 列表
        """
        if not url:
            return []
        try:
            ret = RequestUtils(timeout=60).get_res(url,
                                                   proxies=settings.PROXY if self._proxy else None)
        except Exception as e:
            logger.error(str(e))
            return []
        if not ret or not ret.text:
            return []
        xmls = ret.text
        torrents = []
        try:
            # 解析XML
            dom_tree = xml.dom.minidom.parseString(xmls)
            root_node = dom_tree.documentElement
            items = root_node.getElementsByTagName("item")
            for item in items:
                try:
                    # 标题
                    title = DomUtils.tag_value(item, "title", default="")
                    if not title:
                        continue
                    # 种子链接
                    enclosure = DomUtils.tag_value(item, "enclosure", "url", default="")
                    if not enclosure:
                        continue
                    # 描述
                    description = DomUtils.tag_value(item, "description", default="")
                    # 种子大小
                    size = DomUtils.tag_value(item, "size", default=0)
                    # 种子页面
                    page_url = DomUtils.tag_value(item, "comments", default="")
                    # 发布时间
                    pubdate = DomUtils.tag_value(item, "pubDate", default="")
                    if pubdate:
                        pubdate = StringUtils.unify_datetime_str(pubdate)
                    # 做种数
                    seeders = 0
                    # 下载数
                    peers = 0
                    # imdbid
                    imdbid = ""

                    torznab_attrs = item.getElementsByTagName("torznab:attr")
                    for torznab_attr in torznab_attrs:
                        name = torznab_attr.getAttribute('name')
                        value = torznab_attr.getAttribute('value')
                        if name == "seeders":
                            seeders = value
                        if name == "peers":
                            peers = value
                        if name == "downloadvolumefactor":
                            downloadvolumefactor = value
                            if float(downloadvolumefactor) == 0:
                                freeleech = True
                        if name == "uploadvolumefactor":
                            uploadvolumefactor = value
                        if name == "imdbid":
                            imdbid = value

                    tmp_dict = TorrentInfo(
                        title=title,
                        enclosure=enclosure,
                        description=description,
                        size=size,
                        seeders=seeders,
                        peers=peers,
                        site_name=self.jackett_domain,
                        page_url=page_url,
                        imdbid=imdbid
                    )
                    torrents.append(tmp_dict)
                except Exception as e:
                    logger.error(str(e))
                    continue
        except Exception as e:
            logger.error(f"检索错误：{traceback.format_exc()}")
            pass

        return torrents

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
                                    },
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
                                    }
                                ]
                            },

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
                                            'label': 'Jackett地址',
                                            'placeholder': 'http://127.0.0.1:9117',
                                            'hint': 'Jackett访问地址和端口，如为https需加https://前缀。注意需要先在Jackett中添加indexer，才能正常测试通过和使用'
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
                                            'hint': 'Jackett管理界面右上角复制API Key'
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
                                            'model': 'password',
                                            'label': '密码',
                                            'placeholder': '',
                                            'hint': 'Jackett管理界面中配置的Admin password，如未配置可为空',
                                            'type': 'password'
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
                                                    'indexer - 【JackettExtend】ACG.RIP 搜索出错：NoneType object has no attribute get'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "proxy": False,
            "host": "",
            "api_key": "",
            "password": "",
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
                        'text': site.get("id")
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
                                                        'text': '站点domain'
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
