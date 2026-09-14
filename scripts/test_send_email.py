from botocore.config import Config
from anymail.backends.amazon_ses import EmailBackend
from django.core.mail import EmailMessage
from django.conf import settings
from django.core.mail import send_mail

settings.ANYMAIL["AMAZON_SES_CLIENT_PARAMS"]["config"] = Config(
    connect_timeout=5,
    read_timeout=5,
)

send_mail("Test", "Test body", None, ["stewarmc@jmu.edu"])
