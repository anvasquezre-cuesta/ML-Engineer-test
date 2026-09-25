"""CDK entrypoint: synthesizes the service's stack."""

import aws_cdk

from docintel_infra import config
from docintel_infra import stack


def main() -> None:
    """Builds the app from the deployment settings and synthesizes it."""
    settings = config.InfraSettings()
    app = aws_cdk.App()
    stack.DocintelStack(
        app,
        settings.stack_name,
        settings,
        env=aws_cdk.Environment(region=settings.region),
    )
    app.synth()


if __name__ == "__main__":
    main()
