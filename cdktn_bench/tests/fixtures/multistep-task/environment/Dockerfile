# Toy build context. Never built by the test suite (no docker in `make check`);
# present because AwsBenchTask._validate_layout requires the environment to be
# buildable NOW — a Dockerfile, docker-compose.yaml, or [environment].docker_image.
FROM public.ecr.aws/docker/library/alpine:3.20
