# ALB is locked to CloudFront: ingress only from CloudFront's origin-facing
# prefix list, and every forwarding rule also requires the X-Origin-Verify
# header CloudFront injects. Direct requests to the ALB get the default 403.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  name        = "smart-${var.env}-alb-sg"
  description = "CloudFront-only ingress for smart-${var.env}"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Single rule spanning 80-443 rather than one rule per port: the CloudFront
# origin-facing prefix list counts ~55 entries against the 60-rules SG quota,
# so two rules (80 + 443) would exceed it once certificate_arn is set. Only
# ALB listeners sit behind this SG.
resource "aws_vpc_security_group_ingress_rule" "cloudfront" {
  security_group_id = aws_security_group.alb.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 443
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
}

resource "aws_lb" "main" {
  name                       = "smart-${var.env}-alb"
  internal                   = false
  load_balancer_type         = "application"
  subnets                    = var.public_subnet_ids
  security_groups            = [aws_security_group.alb.id]
  idle_timeout               = var.idle_timeout
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "gateway" {
  name        = "smart-${var.env}-gateway-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30
}

resource "aws_lb_target_group" "frontend" {
  name        = "smart-${var.env}-frontend-tg"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/"
    matcher             = "200-399"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  # No cert: this is the only listener — default to 403, same as HTTPS below.
  dynamic "default_action" {
    for_each = var.certificate_arn == "" ? [1] : []
    content {
      type = "fixed-response"
      fixed_response {
        content_type = "text/plain"
        message_body = "Forbidden"
        status_code  = "403"
      }
    }
  }

  # Cert present: HTTP is redirect-only, HTTPS below holds the real rules.
  dynamic "default_action" {
    for_each = var.certificate_arn != "" ? [1] : []
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = var.certificate_arn != "" ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}

# The active listener: HTTP:80 when no cert, HTTPS:443 when cert is set
# (HTTP:80 is redirect-only in that case) — rules attach to whichever forwards.
locals {
  active_listener_arn = var.certificate_arn == "" ? aws_lb_listener.http.arn : aws_lb_listener.https[0].arn
}

# ALB target group health checks bypass listener rules entirely (they hit the
# target directly), so the X-Origin-Verify requirement below never affects them.

resource "aws_lb_listener_rule" "locales" {
  listener_arn = local.active_listener_arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }

  condition {
    path_pattern {
      values = ["/api/locales", "/api/locales/*"]
    }
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [var.origin_verify_secret]
    }
  }

  # frontend-owned language packs; must win over /api/*
}

resource "aws_lb_listener_rule" "gateway" {
  listener_arn = local.active_listener_arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.gateway.arn
  }

  condition {
    path_pattern {
      values = ["/api/*", "/static/*", "/health"]
    }
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [var.origin_verify_secret]
    }
  }
}

resource "aws_lb_listener_rule" "root" {
  listener_arn = local.active_listener_arn
  priority     = 30

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }

  condition {
    path_pattern {
      values = ["/*"]
    }
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [var.origin_verify_secret]
    }
  }
}
