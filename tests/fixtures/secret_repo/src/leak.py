import os
import anthropic

# Secret fixture is injected by the integration helper after the fixture is copied.
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
