"""The services a real `utux run` uses (M1-14).

The model provider comes from the project's profile, the executor is the
Docker sandbox, and the image and prompts come from the project's domain
pack. In M1 the packs are the `packs/` directory of the utux source tree,
so `utux run` works from a checkout of the repository (installed with
`uv sync`), not from an installed wheel, which has no packs.
"""

from pathlib import Path

import utux
from utux.core.workflow import WorkflowServices
from utux.errors import PackImageError
from utux.executors.docker import DockerExecutor
from utux.executors.image import image_packages, load_recorded_digest
from utux.providers import profiles
from utux.schemas.project_config import load_project_config
from utux.workspace.layout import CONFIG_FILE


def packs_directory() -> Path:
    """The `packs/` directory of the utux source tree."""
    return Path(utux.__file__).resolve().parents[2] / "packs"


def services_for_run(project: Path) -> WorkflowServices:
    """The provider, executor, image and prompts of a project's run.

    Docker is asked here whether it runs rootless, so a run without a
    reachable Docker daemon fails before it starts.

    Raises:
        ContractValidationError: `utux.yaml` is missing or invalid.
        ModelProviderConfigError: The profile has no provider.
        PackImageError: The pack, its prompts or its recorded image is
            missing.
        ExecutorUnavailableError: Docker is missing or unreachable.
    """
    config = load_project_config(project / CONFIG_FILE)
    pack = packs_directory() / config.domain_pack
    prompts = pack / "prompts"
    if not prompts.is_dir():
        raise PackImageError(
            f"the domain pack {config.domain_pack} has no prompts directory at {prompts}; "
            "in M1, utux run works from a checkout of the utux repository"
        )
    image_digest = load_recorded_digest(pack / "image")
    if image_digest is None:
        raise PackImageError(
            f"no image is recorded for the domain pack {config.domain_pack}; build it with "
            f"utux image build {pack / 'image'}"
        )
    provider = profiles.provider_for_profile(
        config.profile, local_base_url=config.local_server.base_url
    )
    executor = DockerExecutor(project)
    return WorkflowServices(
        provider=provider,
        executor=executor,
        image_digest=image_digest,
        locked_packages=image_packages,
        rootless=executor.rootless(),
        prompts=prompts,
        image_directory=pack / "image",
    )
