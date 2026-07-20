from dhanhq import DhanContext, dhanhq

from config.settings import require_credentials


def build_dhan_client() -> dhanhq:
    """Create an authenticated dhanhq client from env credentials."""
    client_id, access_token = require_credentials()
    context = DhanContext(client_id, access_token)
    return dhanhq(context)
