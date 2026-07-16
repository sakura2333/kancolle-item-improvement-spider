import os

REQUEST_WEBSITE = 'https://akashi-list.me/'


def env_enabled(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# 调试/缓存开关：默认值在这里统一修改，也可以用同名环境变量临时覆盖。
# DEBUG: 开启 simple_logger.debug() 输出到 debug.log/output.log。
# CACHE_ONLY: 强制只读本地缓存；缓存缺失时报错，不访问网络。
DEBUG_DEFAULT = False
CACHE_ONLY_DEFAULT = False

DEBUG = env_enabled("DEBUG", DEBUG_DEFAULT)
CACHE_ONLY = env_enabled("CACHE_ONLY", CACHE_ONLY_DEFAULT)


# 1. 定义一个常见的浏览器 UA
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    # "referer": "https://akashi-list.me/",
}

proxies = {
}

xpath_namespace = {"re": "http://exslt.org/regular-expressions"}
