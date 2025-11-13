import logging

__all__ = ["conf_logging"]


DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
FORMAT: str = (
    "[%(asctime)s.%(msecs)03d] %(module)-8s:%(lineno)-8d %(levelname)-8s - %(message)s"
)


def conf_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        datefmt=DATE_FORMAT,
        format=FORMAT,
    )
