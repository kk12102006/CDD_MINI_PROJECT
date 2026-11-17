import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr


logger = logging.getLogger(__name__)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email_address(address):
    return parseaddr(address)[1] == address and bool(
        EMAIL_PATTERN.fullmatch(address)
    )


def send_email(configuration, recipient, subject, body):
    sender = configuration.get("SMTP_EMAIL", "").strip()
    app_password = configuration.get("SMTP_APP_PASSWORD", "").strip()
    if not sender or not app_password:
        logger.warning("Email delivery is not configured.")
        return False, "SMTP_NOT_CONFIGURED"
    if not _valid_email_address(sender) or not _valid_email_address(recipient):
        logger.warning("Email delivery rejected an invalid address.")
        return False, "INVALID_EMAIL_ADDRESS"

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        port = int(configuration.get("SMTP_PORT", 587))
        with smtplib.SMTP(
            configuration.get("SMTP_HOST", "smtp.gmail.com"),
            port,
            timeout=15,
        ) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(sender, app_password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed.")
        return False, "SMTP_AUTHENTICATION_FAILED"
    except smtplib.SMTPRecipientsRefused:
        logger.error("SMTP refused the notification recipient.")
        return False, "SMTP_RECIPIENT_REFUSED"
    except (smtplib.SMTPException, OSError, ssl.SSLError, ValueError) as error:
        error_code = type(error).__name__.upper()
        logger.error("SMTP delivery failed (%s).", error_code)
        return False, error_code

    return True, None
