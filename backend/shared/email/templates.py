"""Email templates for signup, contract expiry, and plan management."""


def signup_verification_email(company_name: str, otp_code: str) -> tuple[str, str]:
    """Generate signup verification email.

    Returns:
        (subject, html_body)
    """
    subject = f"Verify your {company_name} account"
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #333; margin-top: 0;">Welcome to SMART Inventory</h2>
            <p style="color: #666; line-height: 1.6;">
                Hi there! Thank you for signing up <strong>{company_name}</strong> for SMART Inventory Management.
            </p>
            <p style="color: #666; line-height: 1.6;">
                To complete your signup and verify your email address, please use the code below:
            </p>
            <div style="background-color: #f9f9f9; border: 2px solid #007bff; border-radius: 4px; padding: 20px; text-align: center; margin: 30px 0;">
                <p style="font-size: 12px; color: #999; margin-top: 0;">Your verification code is:</p>
                <p style="font-size: 36px; font-weight: bold; color: #007bff; margin: 10px 0; letter-spacing: 5px;">{otp_code}</p>
                <p style="font-size: 12px; color: #999; margin-bottom: 0;">This code expires in 15 minutes.</p>
            </div>
            <p style="color: #666; line-height: 1.6;">
                If you did not sign up for SMART Inventory, please disregard this email.
            </p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #999;">
                SMART Inventory Management<br>
                <a href="https://smart-platform.com" style="color: #007bff; text-decoration: none;">smart-platform.com</a>
            </p>
        </div>
    </body>
    </html>
    """
    return subject, html


def contract_expiry_email(
    tenant_name: str,
    contract_end: str,
    days_remaining: int,
    renewal_url: str,
) -> tuple[str, str]:
    """Generate contract expiry notification email.

    Args:
        tenant_name: name of the tenant/company
        contract_end: contract end date (ISO format "YYYY-MM-DD")
        days_remaining: number of days until expiry (negative if already expired)
        renewal_url: URL to renew the contract

    Returns:
        (subject, html_body)
    """
    if days_remaining <= 0:
        icon = "⚠️"
        status = f"EXPIRED ({abs(days_remaining)} days ago)"
        color = "#dc3545"
        call_to_action = "Renew immediately to restore access"
    else:
        icon = "📅"
        status = f"expires in {days_remaining} days"
        color = "#ffc107"
        call_to_action = f"Renew your contract before {contract_end}"

    subject = f"{icon} {tenant_name}: Contract {status}"

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-left: 4px solid {color};">
            <h2 style="color: #333; margin-top: 0;">Contract Renewal Notice</h2>
            <p style="color: #666; line-height: 1.6;">
                Dear <strong>{tenant_name}</strong> administrator,
            </p>
            <p style="color: #666; line-height: 1.6; font-size: 16px;">
                Your SMART Inventory contract <strong>{status}</strong>.
            </p>
            <p style="color: #666; line-height: 1.6;">
                Contract End Date: <strong style="font-size: 16px;">{contract_end}</strong>
            </p>
            <p style="background-color: {color}; color: white; padding: 15px; border-radius: 4px; margin: 20px 0; line-height: 1.6;">
                {call_to_action}
            </p>
            <p style="color: #666; line-height: 1.6;">
                <strong>Renew your contract now:</strong><br>
                <a href="{renewal_url}" style="display: inline-block; background-color: #007bff; color: white; padding: 10px 20px; border-radius: 4px; text-decoration: none; font-weight: bold;">Renew Contract</a>
            </p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #999;">
                If you have any questions, please contact SMART support at <a href="mailto:support@smart-platform.com" style="color: #007bff; text-decoration: none;">support@smart-platform.com</a>
            </p>
        </div>
    </body>
    </html>
    """
    return subject, html


def plan_upgrade_confirmation_email(
    tenant_name: str,
    old_plan: str,
    new_plan: str,
    effective_date: str,
) -> tuple[str, str]:
    """Generate plan upgrade confirmation email.

    Returns:
        (subject, html_body)
    """
    subject = f"Plan Upgrade Confirmed: {old_plan} → {new_plan}"

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-left: 4px solid #28a745;">
            <h2 style="color: #333; margin-top: 0;">✅ Plan Upgrade Confirmed</h2>
            <p style="color: #666; line-height: 1.6;">
                Dear <strong>{tenant_name}</strong> administrator,
            </p>
            <p style="color: #666; line-height: 1.6;">
                Your plan upgrade has been successfully applied.
            </p>
            <div style="background-color: #f9f9f9; border: 1px solid #ddd; border-radius: 4px; padding: 20px; margin: 20px 0;">
                <p style="margin: 0 0 10px 0; color: #666;">
                    <strong>Previous Plan:</strong> {old_plan}
                </p>
                <p style="margin: 0 0 10px 0; color: #666;">
                    <strong>New Plan:</strong> <span style="font-size: 18px; color: #28a745;">{new_plan}</span>
                </p>
                <p style="margin: 0; color: #666;">
                    <strong>Effective Date:</strong> {effective_date}
                </p>
            </div>
            <p style="color: #666; line-height: 1.6;">
                Your new plan includes enhanced features and higher resource limits. You can start using them immediately.
            </p>
            <p style="color: #666; line-height: 1.6;">
                <strong>Questions?</strong> Visit your <a href="https://app.smart-platform.com/settings/tenant-admin" style="color: #007bff; text-decoration: none;">account settings</a> to view your plan details.
            </p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #999;">
                SMART Inventory Management<br>
                <a href="https://smart-platform.com" style="color: #007bff; text-decoration: none;">smart-platform.com</a>
            </p>
        </div>
    </body>
    </html>
    """
    return subject, html


def password_reset_email(reset_code: str, reset_url: str) -> tuple[str, str]:
    """Generate password reset email.

    Returns:
        (subject, html_body)
    """
    subject = "Reset your SMART Inventory password"

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #333; margin-top: 0;">Reset Your Password</h2>
            <p style="color: #666; line-height: 1.6;">
                We received a request to reset the password for your SMART Inventory account.
            </p>
            <p style="color: #666; line-height: 1.6;">
                If you didn't request this, you can ignore this email. Your password will not change.
            </p>
            <div style="background-color: #f9f9f9; border: 2px solid #007bff; border-radius: 4px; padding: 20px; text-align: center; margin: 30px 0;">
                <p style="font-size: 12px; color: #999; margin-top: 0;">Your reset code is:</p>
                <p style="font-size: 36px; font-weight: bold; color: #007bff; margin: 10px 0; letter-spacing: 5px;">{reset_code}</p>
                <p style="font-size: 12px; color: #999; margin-bottom: 0;">This code expires in 1 hour.</p>
            </div>
            <p style="color: #666; line-height: 1.6;">
                <strong>Or click the link below:</strong><br>
                <a href="{reset_url}" style="display: inline-block; background-color: #007bff; color: white; padding: 10px 20px; border-radius: 4px; text-decoration: none; font-weight: bold;">Reset Password</a>
            </p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #999;">
                If you have any questions, please contact SMART support.
            </p>
        </div>
    </body>
    </html>
    """
    return subject, html
