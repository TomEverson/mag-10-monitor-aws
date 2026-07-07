resource "aws_ecs_cluster" "main" {
  name = "mag10-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "dashboard" {
  name              = "/mag10/dashboard"
  retention_in_days = 30
}

resource "aws_ecs_task_definition" "dashboard" {
  family                   = "mag10-dashboard"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "dashboard"
      image     = var.dashboard_image
      essential = true
      portMappings = [{
        containerPort = 8080
        hostPort      = 8080
        protocol      = "tcp"
      }]
      environment = [
        { name = "AWS_REGION", value = var.aws_region },
      ]
      secrets = [
        {
          name      = "REDSHIFT_SECRET"
          valueFrom = var.redshift_secret_arn
        },
        {
          name      = "DASHBOARD_PASSWORD"
          valueFrom = var.dashboard_secret_arn
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/mag10/dashboard"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_lb" "dashboard" {
  name               = "mag10-dashboard-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]
  subnets            = var.public_subnet_ids
}

resource "aws_lb_target_group" "dashboard" {
  name        = "mag10-dashboard-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/_stcore/health"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
  }
}

resource "aws_lb_listener" "dashboard" {
  load_balancer_arn = aws_lb.dashboard.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.dashboard.arn
  }
}

resource "aws_ecs_service" "dashboard" {
  name            = "mag10-dashboard-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.dashboard.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.dashboard_sg_id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.dashboard.arn
    container_name   = "dashboard"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.dashboard]
}
