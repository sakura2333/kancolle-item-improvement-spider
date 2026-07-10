import inspect
import os

from configs.path import get_log_dir
import logging

from configs.config import DEBUG

# 日志目录
LOG_DIR = get_log_dir()

class WarnOnlyFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == logging.WARNING


class ChannelFilter(logging.Filter):
    """过滤指定 channel 日志"""
    def __init__(self, channel):
        self.channel = channel

    def filter(self, record):
        return getattr(record, "channel", None) == self.channel


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[31m",
    }
    RESET = "\033[0m"

    def format(self, record):
        message = super().format(record)
        color = self.COLORS.get(record.levelno, "")
        return f"{color}{message}{self.RESET}" if color else message


class SimpleLogger:
    def __init__(self, enable=True, debug_enable=True):
        self.ENABLED = enable
        self.DEBUG_ENABLED = debug_enable
        self._logger_cache = {}
        self._setup_logging()

    def _setup_logging(self):
        """初始化日志 handler"""
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root.handlers.clear()

        # 控制台输出
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(ColorFormatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s"))
        root.addHandler(console_handler)

        # 全量日志
        output_handler = logging.FileHandler(os.path.join(LOG_DIR, "output.log"), encoding="utf-8")
        output_handler.setLevel(logging.DEBUG)
        output_handler.setFormatter(formatter)
        root.addHandler(output_handler)

        # debug 日志
        debug_handler = logging.FileHandler(os.path.join(LOG_DIR, "debug.log"), encoding="utf-8")
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.addFilter(ChannelFilter("debug"))
        debug_handler.setFormatter(formatter)
        root.addHandler(debug_handler)

        # warn 日志
        warn_handler = logging.FileHandler(
            os.path.join(LOG_DIR, "warn.log"), encoding="utf-8"
        )
        warn_handler.setLevel(logging.WARNING)
        warn_handler.addFilter(WarnOnlyFilter())
        warn_handler.setFormatter(formatter)
        root.addHandler(warn_handler)

        # error 日志
        error_handler = logging.FileHandler(os.path.join(LOG_DIR, "error.log"), encoding="utf-8")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        root.addHandler(error_handler)

        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("charset_normalizer").setLevel(logging.WARNING)

    def _resolve_name(self, obj=None):
        """自动识别调用类/模块/函数"""
        if obj is not None:
            return obj.__name__ if isinstance(obj, type) else obj.__class__.__name__

        frame = inspect.currentframe()
        try:
            caller = frame.f_back
            while caller:
                locals_ = caller.f_locals
                if "self" in locals_:
                    name = locals_["self"].__class__.__name__
                elif "cls" in locals_:
                    name = locals_["cls"].__name__
                else:
                    mod = inspect.getmodule(caller)
                    name = mod.__name__ if mod and hasattr(mod, "__name__") else caller.f_code.co_name

                if name != "SimpleLogger":
                    return name
                caller = caller.f_back
            return "<unknown>"
        finally:
            del frame

    def _logger(self, obj=None):
        name = self._resolve_name(obj)
        if name not in self._logger_cache:
            self._logger_cache[name] = logging.getLogger(name)
        return self._logger_cache[name]

    def debug(self, msg="", obj=None):
        if self.ENABLED and self.DEBUG_ENABLED:
            self._logger(obj).debug(msg, extra={"channel": "debug"})

    def info(self, msg="", obj=None):
        if self.ENABLED:
            self._logger(obj).info(msg)

    def warn(self, msg="", obj=None):
        if self.ENABLED:
            self._logger(obj).warning(msg)

    def warning(self, msg="", obj=None):
        """Compatibility alias matching the standard logging API."""
        self.warn(msg, obj=obj)

    def error(self, msg="", obj=None):
        if self.ENABLED:
            self._logger(obj).error(msg)


# 全局 logger 实例
simple_logger = SimpleLogger(debug_enable=DEBUG)
