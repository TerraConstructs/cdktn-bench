resource "aws_vpc" "worker" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "worker_a" {
  vpc_id            = aws_vpc.worker.id
  cidr_block        = "10.0.0.0/24"
  availability_zone = "us-east-1a"
}

resource "aws_subnet" "worker_b" {
  vpc_id            = aws_vpc.worker.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "us-east-1b"
}

resource "aws_launch_template" "worker" {
  name          = "cdktn-bench-worker-fleet"
  image_id      = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.small"

  # The ONLY reachable mechanism for tagging launched EBS volumes -- ASG's
  # own tag-propagation mechanism never reaches volumes (see this file's
  # own header comment). Instance is included too so the merge described
  # in AWS's own "EC2 instance tagging lifecycle" doc is redundant, not
  # required, for the instance half here.
  tag_specifications {
    resource_type = "instance"
    tags = {
      CostCenter  = "platform-42"
      Environment = "prod"
    }
  }

  tag_specifications {
    resource_type = "volume"
    tags = {
      CostCenter  = "platform-42"
      Environment = "prod"
    }
  }
}

resource "aws_autoscaling_group" "worker" {
  min_size            = 2
  max_size            = 6
  vpc_zone_identifier = [aws_subnet.worker_a.id, aws_subnet.worker_b.id]

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  # aws_autoscaling_group has NO flat `tags` argument -- only repeated `tag`
  # blocks, each requiring key/value/propagate_at_launch (see this
  # scenario's own tags-only-on-the-asg-resource catch).
  tag {
    key                 = "CostCenter"
    value               = "platform-42"
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = "prod"
    propagate_at_launch = true
  }
}
