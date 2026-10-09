data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

resource "aws_cloudfront_function" "allowlist" {
  count   = length(var.allowed_cidrs) > 0 ? 1 : 0
  name    = "smart-${var.env}-ip-allowlist"
  runtime = "cloudfront-js-2.0"
  publish = true
  code = templatefile("${path.module}/files/ip-allowlist.js.tpl", {
    allowed_cidrs_json = jsonencode(var.allowed_cidrs)
  })
}

resource "aws_cloudfront_distribution" "this" {
  comment      = "smart-${var.env}"
  enabled      = true
  price_class  = "PriceClass_All"
  http_version = "http2and3"
  # The allow-list function is IPv4-only; with IPv6 off, dual-stack browsers
  # fall back to IPv4 instead of being rejected.
  is_ipv6_enabled = length(var.allowed_cidrs) == 0

  origin {
    domain_name = var.alb_dns_name
    origin_id   = "alb"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only" # switch to https-only once the ALB has an ACM cert
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = var.origin_verify_secret
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    compress                 = true
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id

    dynamic "function_association" {
      for_each = length(var.allowed_cidrs) > 0 ? [1] : []
      content {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.allowlist[0].arn
      }
    }
  }

  ordered_cache_behavior {
    path_pattern           = "/_next/static/*"
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_optimized.id

    dynamic "function_association" {
      for_each = length(var.allowed_cidrs) > 0 ? [1] : []
      content {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.allowlist[0].arn
      }
    }
  }

  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    compress                 = true
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id

    # Authorization must reach the gateway — verify login via CloudFront on
    # first AWS run (AllViewer forwards all headers, incl. Authorization).
    dynamic "function_association" {
      for_each = length(var.allowed_cidrs) > 0 ? [1] : []
      content {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.allowlist[0].arn
      }
    }
  }

  ordered_cache_behavior {
    path_pattern             = "/static/*"
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    compress                 = true
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id

    dynamic "function_association" {
      for_each = length(var.allowed_cidrs) > 0 ? [1] : []
      content {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.allowlist[0].arn
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
