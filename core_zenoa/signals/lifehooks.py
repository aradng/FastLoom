from core_zenoa.db.schemas import BaseDocument
from core_zenoa.db.signals import Operations, SignalsSave, SignalsUpdate


async def init_streams(models: list[BaseDocument]):
    model_cls: type[SignalsSave] | type[SignalsUpdate]
    for model_cls in filter(lambda c: issubclass(c, SignalsSave), models):
        model_cls.get_publisher(Operations.SAVE)
    for model_cls in filter(lambda c: issubclass(c, SignalsUpdate), models):
        model_cls.get_publisher(Operations.UPDATE)
