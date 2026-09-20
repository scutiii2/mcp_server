import json

from src.services.sse import encode_sse, stream_async_generator


def test_encode_sse_shape():
    assert encode_sse({"type": "token", "text": "hi"}) == b'data: {"type": "token", "text": "hi"}\n\n'


def test_stream_async_generator_yields_in_order():
    async def factory():
        async def gen():
            yield {"type": "step_start", "id": "1"}
            yield {"type": "final", "response": "ok"}
        async for item in gen():
            yield item

    items = list(stream_async_generator(factory))
    assert items == [{"type": "step_start", "id": "1"}, {"type": "final", "response": "ok"}]


def test_stream_async_generator_turns_an_exception_into_an_error_event():
    async def factory():
        raise RuntimeError("boom")
        yield  # pragma: no cover - unreachable, makes this an async generator

    items = list(stream_async_generator(factory))
    assert items == [{"type": "error", "message": "boom"}]
