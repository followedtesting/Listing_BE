import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any, Tuple
from config import settings

logger = logging.getLogger(__name__)

def generate_email_html(report_data: List[Dict[str, Any]]) -> str:
    """
    Generates a modern, responsive HTML email digest for job listings.
    
    Includes:
    - Portal section for portals with report_items.
    - Badges for 'NEW LISTINGS' vs 'INITIAL SETUP / BASELINE' (when both were 0 earlier).
    - Styled HTML buttons for every job listing URL.
    """
    total_portals = len(report_data)
    portals_with_jobs = [r for r in report_data if r.get("report_items") and len(r["report_items"]) > 0]
    total_reported_jobs = sum(len(r.get("report_items", [])) for r in report_data)
    
    portal_sections_html = ""
    
    if not portals_with_jobs:
        portal_sections_html = """
        <div style="background-color: #FFFFFF; border-radius: 8px; padding: 30px; text-align: center; border: 1px solid #E2E8F0; margin-bottom: 20px;">
            <p style="color: #64748B; font-size: 16px; margin: 0;">
                ℹ️ No new or baseline job listings detected across active portals during this sequential run.
            </p>
        </div>
        """
    else:
        for r in portals_with_jobs:
            portal_name = r.get("portal_name", "Career Portal")
            was_both_zero = r.get("was_both_zero_earlier", False)
            items = r.get("report_items", [])
            
            badge_text = "INITIAL SETUP / BASELINE" if was_both_zero else "NEW LISTINGS"
            badge_color = "#0284C7" if was_both_zero else "#16A34A"
            badge_bg = "#E0F2FE" if was_both_zero else "#DCFCE7"
            
            rows_html = ""
            for idx, job in enumerate(items, 1):
                role_name = job.get("role_name", "Job Listing")
                jobid = job.get("jobid", "N/A")
                link = job.get("job_listing_link", "#")
                
                rows_html += f"""
                <tr style="border-bottom: 1px solid #F1F5F9;">
                    <td style="padding: 12px; font-size: 13px; color: #64748B; width: 30px;">{idx}</td>
                    <td style="padding: 12px; font-size: 14px; color: #0F172A; font-weight: 600;">{role_name}</td>
                    <td style="padding: 12px; font-size: 13px; color: #475569;"><span style="background-color: #F1F5F9; padding: 2px 8px; border-radius: 4px; font-family: monospace;">{jobid}</span></td>
                    <td style="padding: 12px; text-align: right;">
                        <a href="{link}" target="_blank" style="background-color: #2563EB; color: #FFFFFF; text-decoration: none; padding: 6px 14px; border-radius: 6px; font-weight: 600; font-size: 12px; display: inline-block;">View Job &rarr;</a>
                    </td>
                </tr>
                """
                
            portal_sections_html += f"""
            <div style="background-color: #FFFFFF; border-radius: 8px; padding: 20px; border: 1px solid #E2E8F0; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #F1F5F9; padding-bottom: 12px; margin-bottom: 16px;">
                    <h3 style="margin: 0; font-size: 18px; color: #0F172A;">{portal_name}</h3>
                    <span style="background-color: {badge_bg}; color: {badge_color}; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">
                        {badge_text} ({len(items)})
                    </span>
                </div>
                <table style="width: 100%; border-collapse: collapse; text-align: left;">
                    <thead>
                        <tr style="border-bottom: 1px solid #CBD5E1; font-size: 12px; color: #64748B; text-transform: uppercase;">
                            <th style="padding: 8px;">#</th>
                            <th style="padding: 8px;">Role Title</th>
                            <th style="padding: 8px;">Job ID</th>
                            <th style="padding: 8px; text-align: right;">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
            """
            
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Job Tracker Sequential Digest</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F8FAFC; margin: 0; padding: 20px; color: #1E293B;">
        <div style="max-width: 680px; margin: 0 auto; background-color: #F8FAFC;">
            
            <!-- Header -->
            <div style="background-color: #0F172A; border-radius: 12px 12px 0 0; padding: 28px 24px; text-align: center; color: #FFFFFF;">
                <h1 style="margin: 0 0 6px 0; font-size: 24px; font-weight: 700; letter-spacing: -0.5px;">🎯 Job Listing Tracker Digest</h1>
                <p style="margin: 0; font-size: 14px; color: #94A3B8;">Sequential Adapter Scan Results & Notifications</p>
            </div>
            
            <!-- Summary Banner -->
            <div style="background-color: #3B82F6; padding: 16px 24px; color: #FFFFFF; font-size: 14px; font-weight: 500;">
                📊 Summary: Scraped <strong>{total_portals}</strong> portals | Reported <strong>{total_reported_jobs}</strong> total listing item(s) across <strong>{len(portals_with_jobs)}</strong> portal(s).
            </div>
            
            <!-- Content Sections -->
            <div style="padding: 24px 0;">
                {portal_sections_html}
            </div>
            
            <!-- Footer -->
            <div style="text-align: center; padding: 20px; font-size: 12px; color: #94A3B8; border-top: 1px solid #E2E8F0;">
                Sent automatically by Antigravity Job Tracker • Local Sequential Adapter Scan
            </div>
            
        </div>
    </body>
    </html>
    """
    return html_template

def send_html_email(subject: str, html_content: str, recipient: str = None) -> Tuple[bool, str]:
    """
    Sends an HTML email using configured SMTP settings.
    Returns (success: bool, message: str).
    """
    smtp_host = settings.SMTP_HOST
    smtp_port = settings.SMTP_PORT
    smtp_user = settings.SMTP_USER
    smtp_password = settings.SMTP_PASSWORD
    email_from = settings.EMAIL_FROM or smtp_user
    email_to = recipient or settings.EMAIL_TO or smtp_user
    
    if not smtp_user or not smtp_password or not email_to:
        msg = "SMTP credentials not configured in environment (.env). Skipping SMTP dispatch. HTML report generated successfully."
        logger.warning(msg)
        return False, msg
        
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = email_from
        msg["To"] = email_to
        
        part_html = MIMEText(html_content, "html", "utf-8")
        msg.attach(part_html)
        
        logger.info(f"Connecting to SMTP server {smtp_host}:{smtp_port}...")
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
            
        success_msg = f"Email digest sent successfully to {email_to}"
        logger.info(success_msg)
        return True, success_msg
    except Exception as e:
        error_msg = f"Failed to send email via SMTP: {e}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg
