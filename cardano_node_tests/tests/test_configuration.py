"""Tests for node configuration."""
import json
import logging
import time
from pathlib import Path

import allure
import pytest
from _pytest.tmpdir import TempdirFactory
from cardano_clusterlib import clusterlib

from cardano_node_tests.utils import cluster_management
from cardano_node_tests.utils import cluster_nodes
from cardano_node_tests.utils import configuration
from cardano_node_tests.utils import helpers

LOGGER = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def create_temp_dir(tmp_path_factory: TempdirFactory):
    """Create a temporary dir."""
    p = Path(tmp_path_factory.getbasetemp()).joinpath(helpers.get_id_for_mktemp(__file__)).resolve()
    p.mkdir(exist_ok=True, parents=True)
    return p


@pytest.fixture
def temp_dir(create_temp_dir: Path):
    """Change to a temporary dir."""
    with helpers.change_cwd(create_temp_dir):
        yield create_temp_dir


@pytest.fixture(scope="module")
def epoch_length_start_cluster(tmp_path_factory: TempdirFactory) -> Path:
    """Update *epochLength* to 1200."""
    pytest_globaltemp = helpers.get_pytest_globaltemp(tmp_path_factory)

    # need to lock because this same fixture can run on several workers in parallel
    with helpers.FileLockIfXdist(f"{pytest_globaltemp}/startup_files_epoch_1200.lock"):
        destdir = pytest_globaltemp / "startup_files_epoch_1200"
        destdir.mkdir(exist_ok=True)

        # return existing script if it is already generated by other worker
        destdir_ls = list(destdir.glob("start-cluster*"))
        if destdir_ls:
            return destdir_ls[0]

        startup_files = cluster_nodes.get_cluster_type().cluster_scripts.copy_scripts_files(
            destdir=destdir
        )
        with open(startup_files.genesis_spec) as fp_in:
            genesis_spec = json.load(fp_in)

        genesis_spec["epochLength"] = 1200

        with open(startup_files.genesis_spec, "w") as fp_out:
            json.dump(genesis_spec, fp_out)

        return startup_files.start_script


@pytest.fixture(scope="module")
def slot_length_start_cluster(tmp_path_factory: TempdirFactory) -> Path:
    """Update *slotLength* to 0.3."""
    pytest_globaltemp = helpers.get_pytest_globaltemp(tmp_path_factory)

    # need to lock because this same fixture can run on several workers in parallel
    with helpers.FileLockIfXdist(f"{pytest_globaltemp}/startup_files_slot_03.lock"):
        destdir = pytest_globaltemp / "startup_files_slot_03"
        destdir.mkdir(exist_ok=True)

        # return existing script if it is already generated by other worker
        destdir_ls = list(destdir.glob("start-cluster*"))
        if destdir_ls:
            return destdir_ls[0]

        startup_files = cluster_nodes.get_cluster_type().cluster_scripts.copy_scripts_files(
            destdir=destdir
        )
        with open(startup_files.genesis_spec) as fp_in:
            genesis_spec = json.load(fp_in)

        genesis_spec["slotLength"] = 0.3

        with open(startup_files.genesis_spec, "w") as fp_out:
            json.dump(genesis_spec, fp_out)

        return startup_files.start_script


@pytest.fixture
def cluster_epoch_length(
    cluster_manager: cluster_management.ClusterManager, epoch_length_start_cluster: Path
) -> clusterlib.ClusterLib:
    return cluster_manager.get(
        singleton=True, cleanup=True, start_cmd=str(epoch_length_start_cluster)
    )


@pytest.fixture
def cluster_slot_length(
    cluster_manager: cluster_management.ClusterManager, slot_length_start_cluster: Path
) -> clusterlib.ClusterLib:
    return cluster_manager.get(
        singleton=True, cleanup=True, start_cmd=str(slot_length_start_cluster)
    )


# use the "temp_dir" fixture for all tests automatically
pytestmark = pytest.mark.usefixtures("temp_dir")


def check_epoch_length(cluster_obj: clusterlib.ClusterLib) -> None:
    end_sec = 15
    cluster_obj.wait_for_new_epoch()
    epoch_no = cluster_obj.get_last_block_epoch()
    time.sleep((cluster_obj.slot_length * cluster_obj.epoch_length) - end_sec)
    assert epoch_no == cluster_obj.get_last_block_epoch()
    time.sleep(end_sec)
    assert epoch_no + 1 == cluster_obj.get_last_block_epoch()


@pytest.mark.run(order=3)
@pytest.mark.skipif(
    bool(configuration.TX_ERA),
    reason="different TX eras doesn't affect this test, pointless to run",
)
class TestBasic:
    """Basic tests for node configuration."""

    @allure.link(helpers.get_vcs_link())
    def test_epoch_length(self, cluster_epoch_length: clusterlib.ClusterLib):
        """Test the *epochLength* configuration."""
        cluster = cluster_epoch_length

        assert cluster.slot_length == 0.2
        assert cluster.epoch_length == 1200
        check_epoch_length(cluster)

    @pytest.mark.run(order=2)
    @allure.link(helpers.get_vcs_link())
    def test_slot_length(self, cluster_slot_length: clusterlib.ClusterLib):
        """Test the *slotLength* configuration."""
        cluster = cluster_slot_length

        assert cluster.slot_length == 0.3
        assert cluster.epoch_length == 1000
        check_epoch_length(cluster)
