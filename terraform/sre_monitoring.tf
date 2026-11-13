terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

# On-Call Alert Notification Topic (Connects to PagerDuty / Slack / Email)
resource "aws_sns_topic" "sre_oncall" {
  name = "pulsepay-prod-sre-oncall-alerts"
}

# CloudWatch Alarm: Triggers if HTTP 5xx Error Rate exceeds 1% (Error Budget Burn)
resource "aws_cloudwatch_metric_alarm" "high_5xx_error_rate" {
  alarm_name          = "pulsepay-prod-5xx-slo-breach"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "PulsePay 5xx error rate breached SLO error budget threshold"
  alarm_actions       = [aws_sns_topic.sre_oncall.arn]
}

# CloudWatch Alarm: Triggers if p95 Latency exceeds 250ms (0.25s)
resource "aws_cloudwatch_metric_alarm" "high_p95_latency" {
  alarm_name          = "pulsepay-prod-p95-latency-slo-breach"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p95"
  threshold           = 0.25
  alarm_description   = "PulsePay p95 latency exceeded 250ms SLO target"
  alarm_actions       = [aws_sns_topic.sre_oncall.arn]
}

# Automated Horizontal Scaling (Handles traffic spikes without human intervention)
resource "aws_appautoscaling_target" "ecs_target" {
  max_capacity       = 10
  min_capacity       = 2
  resource_id        = "service/pulsepay-prod-cluster/pulsepay-prod-service"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "ecs_cpu_policy" {
  name               = "pulsepay-prod-cpu-autoscaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs_target.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs_target.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs_target.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
