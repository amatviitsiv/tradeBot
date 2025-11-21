import logging, sys
from logging.handlers import RotatingFileHandler
import config as cfg

def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = RotatingFileHandler(cfg.LOG_FILE, maxBytes=cfg.LOG_MAX_BYTES, backupCount=cfg.LOG_BACKUP_COUNT)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    th = RotatingFileHandler(cfg.TRADES_LOG_FILE, maxBytes=cfg.LOG_MAX_BYTES, backupCount=cfg.LOG_BACKUP_COUNT)
    th.setFormatter(fmt)
    trades_logger = logging.getLogger("trades")
    trades_logger.setLevel(logging.INFO)
    trades_logger.addHandler(th)
    eh = RotatingFileHandler(cfg.ERROR_LOG_FILE, maxBytes=cfg.LOG_MAX_BYTES, backupCount=cfg.LOG_BACKUP_COUNT)
    eh.setFormatter(fmt)
    errors_logger = logging.getLogger("errors")
    errors_logger.setLevel(logging.WARNING)
    errors_logger.addHandler(eh)
    return root

logger = setup_logging()
