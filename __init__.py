"""Hermes registration. No networking, model calls, or prompt changes at load time."""
from .spend import SpendPlugin
from threading import Lock


def register(ctx):
    # Registration is declarative: open the ledger only when a scoped callback runs.
    plugin = None
    lock = Lock()

    def get_plugin():
        nonlocal plugin
        with lock:
            if plugin is None:
                plugin = SpendPlugin(ctx.state.data_dir, ctx.get_config, profile=ctx.profile_name)
            return plugin

    def callback(method):
        def invoke(*args, **kwargs):
            return getattr(get_plugin(), method)(*args, **kwargs)
        return invoke

    command = callback("command")
    ctx.register_middleware("llm_execution", callback("on_execution"))
    ctx.register_hook("pre_api_request", callback("on_pre_request"))
    ctx.register_hook("api_request_error", callback("on_error"))
    ctx.register_hook("post_auxiliary_call", callback("on_auxiliary"))
    ctx.register_hook("post_tool_call", callback("on_image_tool"))
    ctx.register_command(
        "spend", command,
        description="OpenRouter API-key spend and Hermes request costs",
        args_hint="[today|week|month|total|refresh|ledger|models|status|reconcile|help]",
    )

    def setup(parser):
        parser.add_argument("args", nargs="*", help="Same options as /spend")

    def handle(args):
        result = command(" ".join(args.args))
        print(result)
        return 1 if result.startswith("Error:") else 0

    ctx.register_cli_command(
        "spend", help="Show OpenRouter spend without making an LLM call",
        setup_fn=setup, handler_fn=handle,
    )
