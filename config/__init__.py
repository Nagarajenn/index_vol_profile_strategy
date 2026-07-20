# This machine's antivirus (Norton) performs TLS interception on all outbound
# HTTPS with a locally-generated root CA that Windows trusts but Python's
# bundled certifi list does not. truststore makes the ssl module defer to the
# OS certificate store instead, so plain `requests` calls verify correctly.
# Must run before any `requests`/`urllib3` HTTPS call happens anywhere in the app.
import truststore

truststore.inject_into_ssl()
