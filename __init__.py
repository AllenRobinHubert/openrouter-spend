"""Hermes registration. No networking, model calls, or prompt changes at load time."""
from .spend import SpendPlugin


def register(ctx):
    plugin = SpendPlugin(ctx.state.data_dir, ctx.get_config, profile=ctx.profile_name)
    ctx.register_middleware("llm_execution", plugin.on_execution)
    ctx.register_hook("pre_api_request", plugin.on_pre_request)
    ctx.register_hook("api_request_error", plugin.on_error)
    ctx.register_hook("post_auxiliary_call", plugin.on_auxiliary)
    ctx.register_hook("post_tool_call", plugin.on_image_tool)
    ctx.register_command(
        "spend", plugin.command,
        description="OpenRouter API-key spend and Hermes request costs",
        args_hint="[today|week|month|total|refresh|ledger|models|status|reconcile|help]",
    )

    def setup(parser):
        parser.add_argument("args", nargs="*", help="Same options as /spend")

    def handle(args):
        result = plugin.command(" ".join(args.args))
        print(result)
        return 1 if result.startswith("Error:") else 0

    ctx.register_cli_command(
        "spend", help="Show OpenRouter spend without making an LLM call",
        setup_fn=setup, handler_fn=handle,
    )
