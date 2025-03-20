from core_bluprint.db.schemas import BaseDocument
from core_bluprint.db.signals import Operations, SignalsSave, SignalsUpdate


async def init_streams(models: list[BaseDocument]):
    for model__save_cls in filter(
        lambda c: issubclass(c, SignalsSave), models
    ):
        model__save_cls.get_publisher(Operations.SAVE)
    for model_update_cls in filter(
        lambda c: issubclass(c, SignalsUpdate), models
    ):
        model_update_cls.get_publisher(Operations.UPDATE)
