import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from server.config import SMTPConfig

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, cfg: SMTPConfig | None):
        self.cfg = cfg

    def send(self, subject: str, body: str, timeout: float = 10.0) -> tuple[bool, str]:
        if not self.cfg:
            logger.info("Email notifier disabled (no SMTP config)")
            return False, "no smtp config"

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.cfg.from_addr
        msg["To"] = ", ".join(self.cfg.to_addrs)
        try:
            if self.cfg.port == 465:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.cfg.host, self.cfg.port, timeout=timeout, context=context) as server:
                    server.login(self.cfg.username, self.cfg.password)
                    server.sendmail(self.cfg.from_addr, self.cfg.to_addrs, msg.as_string())
            elif self.cfg.use_tls:
                with smtplib.SMTP(self.cfg.host, self.cfg.port, timeout=timeout) as server:
                    server.starttls()
                    server.login(self.cfg.username, self.cfg.password)
                    server.sendmail(self.cfg.from_addr, self.cfg.to_addrs, msg.as_string())
            else:
                with smtplib.SMTP(self.cfg.host, self.cfg.port, timeout=timeout) as server:
                    server.sendmail(self.cfg.from_addr, self.cfg.to_addrs, msg.as_string())
            return True, "sent"
        except Exception as e:
            logger.error("Failed to send email: %s", e)
            return False, str(e)


# backward compat function
def send_email(subject: str, body: str, smtp_cfg: SMTPConfig, timeout: float = 10.0) -> bool:
    notifier = EmailNotifier(smtp_cfg)
    ok, _ = notifier.send(subject, body, timeout)
    return ok
