resource "aws_security_group" "alb" {
  name        = "smart-${var.env}-alb-sg"
  description = "Internet-facing ALB ingress for smart-${var.env}"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  for_each          = toset(var.allowed_cidrs)
  security_group_id = aws_security_group.alb.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  for_each          = var.certificate_arn != "" ? toset(var.allowed_cidrs) : toset([])
  security_group_id = aws_security_group.alb.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = each.value
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

  dynamic "default_action" {
    for_each = var.certificate_arn == "" ? [1] : []
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.frontend.arn
    }
  }

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
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

# The active listener: HTTP:80 when no cert, HTTPS:443 when cert is set
# (HTTP:80 is redirect-only in that case) — rules attach to whichever forwards.
locals {
  active_listener_arn = var.certificate_arn == "" ? aws_lb_listener.http.arn : aws_lb_listener.https[0].arn
}

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
}
