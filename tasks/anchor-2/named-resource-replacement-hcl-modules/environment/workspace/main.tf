module "internal_services" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name = "internal-services"
  cidr = "10.20.0.0/16"

  azs                  = ["us-east-1a"]
  private_subnets      = ["10.20.1.0/24"]
  private_subnet_names = ["internal-services-a"]

  enable_dns_support   = true
  enable_dns_hostnames = true
}

resource "aws_security_group" "ssm_endpoint" {
  name        = "internal-services-ssm-endpoint"
  description = "HTTPS from the internal services subnet to the SSM interface endpoint"
  vpc_id      = module.internal_services.vpc_id

  ingress {
    description = "HTTPS from the internal services VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.20.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "internal-services-ssm-endpoint"
  }
}

module "ssm_endpoint" {
  source  = "terraform-aws-modules/vpc/aws//modules/vpc-endpoints"
  version = "6.7.3"

  region = "us-east-1"

  vpc_id             = module.internal_services.vpc_id
  subnet_ids         = module.internal_services.private_subnets
  security_group_ids = [aws_security_group.ssm_endpoint.id]

  endpoints = {
    ssm = {
      service_endpoint    = "com.amazonaws.us-east-1.ssm"
      private_dns_enabled = true
      tags = {
        Name = "internal-services-ssm"
      }
    }
  }
}
