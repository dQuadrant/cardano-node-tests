import contextlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Generator
from typing import List
from typing import Optional

import pytest
from _pytest.fixtures import FixtureRequest

from cardano_node_tests.utils import clusterlib
from cardano_node_tests.utils.types import FileType
from cardano_node_tests.utils.types import UnpackableSequence

LOGGER = logging.getLogger(__name__)


def wait_for(func, delay=5, num_sec=180, message=None):
    """Wait for success of `func` for `num_sec`."""
    end_time = time.time() + num_sec

    while time.time() < end_time:
        response = func()
        if response:
            return response
        time.sleep(delay)

    pytest.fail(f"Failed to {message or 'finish'} in time.")


@contextlib.contextmanager
def change_cwd(path: FileType) -> Generator[FileType, None, None]:
    """Change and restore CWD - context manager."""
    orig_cwd = os.getcwd()
    os.chdir(path)
    LOGGER.debug(f"Changed CWD to '{path}'.")
    try:
        yield path
    finally:
        os.chdir(orig_cwd)
        LOGGER.debug(f"Restored CWD to '{orig_cwd}'.")


def read_address_from_file(location: FileType) -> str:
    """Read address stored in file."""
    with open(Path(location).expanduser()) as in_file:
        return in_file.read().strip()


def write_json(location: FileType, content: dict) -> FileType:
    """Write distionary content to JSON file."""
    with open(Path(location).expanduser(), "w") as out_file:
        out_file.write(json.dumps(content))
    return location


def run_shell_command(command: str, workdir: FileType = ""):
    """Run command in shell."""
    cmd = f"bash -c '{command}'"
    cmd = cmd if not workdir else f"cd {workdir}; {cmd}"
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    __, stderr = p.communicate()
    if p.returncode != 0:
        raise AssertionError(f"An error occurred while running `{cmd}`: {stderr.decode()}")


def fund_from_genesis(
    *dst_addrs: UnpackableSequence,
    cluster_obj: clusterlib.ClusterLib,
    amount: int = 2_000_000,
    tx_name: Optional[str] = None,
    destination_dir: FileType = ".",
):
    """Send `amount` from genesis addr to all `dst_addrs`."""
    tx_name = tx_name or clusterlib.get_timestamped_rand_str()
    tx_name = f"{tx_name}_genesis_funding"
    fund_dst = [clusterlib.TxOut(address=d, amount=amount) for d in dst_addrs]
    fund_tx_files = clusterlib.TxFiles(
        signing_key_files=[cluster_obj.delegate_skey, cluster_obj.genesis_utxo_skey]
    )
    cluster_obj.send_funds(
        src_address=cluster_obj.genesis_utxo_addr,
        destinations=fund_dst,
        tx_name=tx_name,
        tx_files=fund_tx_files,
        destination_dir=destination_dir,
    )
    cluster_obj.wait_for_new_tip(new_blocks=2)


def return_funds_to_faucet(
    *src_addrs: clusterlib.AddressRecord,
    cluster_obj: clusterlib.ClusterLib,
    faucet_addr: str,
    amount: int = -1,
    tx_name: Optional[str] = None,
    destination_dir: FileType = ".",
):
    """Send `amount` from all `src_addrs` to `faucet_addr`.

    The amount of "-1" means all available funds.
    """
    tx_name = tx_name or clusterlib.get_timestamped_rand_str()
    tx_name = f"{tx_name}_return_funds"
    try:
        logging.disable(logging.ERROR)
        for src in src_addrs:
            fund_dst = [clusterlib.TxOut(address=faucet_addr, amount=amount)]
            fund_tx_files = clusterlib.TxFiles(signing_key_files=[src.skey_file])
            # try to return funds; don't mind if there's not enough funds for fees etc.
            try:
                cluster_obj.send_funds(
                    src_address=src.address,
                    destinations=fund_dst,
                    tx_name=tx_name,
                    tx_files=fund_tx_files,
                    destination_dir=destination_dir,
                )
            except clusterlib.CLIError:
                pass
    finally:
        logging.disable(logging.NOTSET)
    cluster_obj.wait_for_new_tip(new_blocks=2)


def fund_from_faucet(
    *dst_addrs: clusterlib.AddressRecord,
    cluster_obj: clusterlib.ClusterLib,
    faucet_data: dict,
    amount: int = 3_000_000,
    tx_name: Optional[str] = None,
    request: Optional[FixtureRequest] = None,
    destination_dir: FileType = ".",
):
    """Send `amount` from faucet addr to all `dst_addrs`."""
    if request:
        request.addfinalizer(
            lambda: return_funds_to_faucet(
                *dst_addrs,
                cluster_obj=cluster_obj,
                faucet_addr=faucet_data["payment_addr"],
                tx_name=tx_name,
                destination_dir=destination_dir,
            )
        )

    tx_name = tx_name or clusterlib.get_timestamped_rand_str()
    tx_name = f"{tx_name}_funding"
    fund_dst = [clusterlib.TxOut(address=d.address, amount=amount) for d in dst_addrs]
    fund_tx_files = clusterlib.TxFiles(
        signing_key_files=[faucet_data["payment_key_pair"].skey_file]
    )

    cluster_obj.send_funds(
        src_address=faucet_data["payment_addr"],
        destinations=fund_dst,
        tx_name=tx_name,
        tx_files=fund_tx_files,
        destination_dir=destination_dir,
    )
    cluster_obj.wait_for_new_tip(new_blocks=2)


def create_payment_addrs(
    *names: UnpackableSequence,
    cluster_obj: clusterlib.ClusterLib,
    stake_vkey_file: Optional[FileType] = None,
    destination_dir: FileType = ".",
) -> List[clusterlib.AddressRecord]:
    """Create new payment address(es)."""
    addrs = [
        cluster_obj.gen_payment_addr_and_keys(
            name=name, stake_vkey_file=stake_vkey_file, destination_dir=destination_dir,
        )
        for name in names
    ]

    LOGGER.debug(f"Created {len(addrs)} payment address(es)")
    return addrs


def create_stake_addrs(
    *names: UnpackableSequence, cluster_obj: clusterlib.ClusterLib, destination_dir: FileType = ".",
) -> List[clusterlib.AddressRecord]:
    """Create new stake address(es)."""
    addrs = [
        cluster_obj.gen_stake_addr_and_keys(name=name, destination_dir=destination_dir,)
        for name in names
    ]

    LOGGER.debug(f"Created {len(addrs)} stake address(es)")
    return addrs


def load_devops_pools_data():
    """Load data for pools existing in the devops environment."""
    data_dir = get_cluster_env()["state_dir"] / "nodes"
    pools = ("node-pool1", "node-pool2")

    addrs_data = {}
    for addr_name in pools:
        addr_data_dir = data_dir / addr_name
        addrs_data[addr_name] = {
            "payment_key_pair": clusterlib.KeyPair(
                vkey_file=addr_data_dir / "owner-utxo.vkey",
                skey_file=addr_data_dir / "owner-utxo.skey",
            ),
            "stake_key_pair": clusterlib.KeyPair(
                vkey_file=addr_data_dir / "owner-stake.vkey",
                skey_file=addr_data_dir / "owner-stake.skey",
            ),
            "payment_addr": read_address_from_file(addr_data_dir / "owner.addr"),
            "stake_addr": read_address_from_file(addr_data_dir / "owner-stake.addr"),
            "stake_addr_registration_cert": read_address_from_file(
                addr_data_dir / "stake.reg.cert"
            ),
            "cold_key_pair": clusterlib.ColdKeyPair(
                vkey_file=addr_data_dir / "cold.vkey",
                skey_file=addr_data_dir / "cold.skey",
                counter_file=addr_data_dir / "cold.counter",
            ),
        }

    return addrs_data


def get_cluster_env() -> dict:
    """Get cardano cluster environment."""
    socket_path = Path(os.environ["CARDANO_NODE_SOCKET_PATH"]).expanduser().resolve()
    state_dir = socket_path.parent
    work_dir = state_dir.parent
    repo_dir = Path(os.environ.get("CARDANO_NODE_REPO_PATH") or work_dir)

    cluster_env = {
        "socket_path": socket_path,
        "state_dir": state_dir,
        "repo_dir": repo_dir,
        "work_dir": work_dir,
    }
    return cluster_env


def wait_for_stake_distribution(cluster_obj: clusterlib.ClusterLib):
    """Wait to 3rd epoch (if necessary) and return stake distribution info."""
    last_block_epoch = cluster_obj.get_last_block_epoch()
    if last_block_epoch < 3:
        new_epochs = 3 - last_block_epoch
        LOGGER.info(f"Waiting {new_epochs} epoch(s) to get stake distribution.")
        cluster_obj.wait_for_new_epoch(new_epochs=new_epochs)
    return cluster_obj.get_stake_distribution()


def setup_test_addrs(cluster_obj: clusterlib.ClusterLib, destination_dir: FileType = ".",) -> dict:
    """Create addresses and their keys for usage in tests."""
    destination_dir = Path(destination_dir).expanduser()
    destination_dir.mkdir(parents=True, exist_ok=True)
    addrs = ("user1", "pool-owner1")

    LOGGER.debug("Creating addresses and keys for tests.")
    addrs_data = {}
    for addr_name in addrs:
        payment_key_pair = cluster_obj.gen_payment_key_pair(
            key_name=addr_name, destination_dir=destination_dir,
        )
        stake_key_pair = cluster_obj.gen_stake_key_pair(
            key_name=addr_name, destination_dir=destination_dir,
        )
        payment_addr = cluster_obj.gen_payment_addr(
            payment_vkey_file=payment_key_pair.vkey_file, stake_vkey_file=stake_key_pair.vkey_file,
        )
        stake_addr = cluster_obj.gen_stake_addr(stake_vkey_file=stake_key_pair.vkey_file)
        stake_addr_registration_cert = cluster_obj.gen_stake_addr_registration_cert(
            addr_name=addr_name,
            stake_vkey_file=stake_key_pair.vkey_file,
            destination_dir=destination_dir,
        )

        addrs_data[addr_name] = {
            "payment_key_pair": payment_key_pair,
            "stake_key_pair": stake_key_pair,
            "payment_addr": payment_addr,
            "stake_addr": stake_addr,
            "stake_addr_registration_cert": stake_addr_registration_cert,
        }

    LOGGER.debug("Funding created addresses." "")
    fund_from_genesis(
        *[d["payment_addr"] for d in addrs_data.values()],
        cluster_obj=cluster_obj,
        amount=20_000_000_000,
        destination_dir=destination_dir,
    )

    pools_data = load_devops_pools_data()
    return {**addrs_data, **pools_data}


def start_cluster() -> clusterlib.ClusterLib:
    """Start cluster."""
    LOGGER.info("Starting cluster.")
    cluster_env = get_cluster_env()
    run_shell_command("start-cluster", workdir=cluster_env["work_dir"])
    LOGGER.info("Cluster started.")

    return clusterlib.ClusterLib(cluster_env["state_dir"])


def stop_cluster():
    """Stop cluster."""
    LOGGER.info("Stopping cluster.")
    cluster_env = get_cluster_env()
    try:
        run_shell_command("stop-cluster", workdir=cluster_env["work_dir"])
    except Exception as exc:
        LOGGER.debug(f"Failed to stop cluster: {exc}")


def start_stop_cluster(request: FixtureRequest) -> clusterlib.ClusterLib:
    """Stop cluster if needed, start fresh cluster, stop cluster at scope end."""
    stop_cluster()
    request.addfinalizer(stop_cluster)
    cluster_obj = start_cluster()
    return cluster_obj


def check_pool_data(  # noqa: C901
    pool_ledger_state: dict, pool_creation_data: clusterlib.PoolData
) -> str:
    """Check that actual pool state corresponds with pool creation data."""
    errors_list = []

    if pool_ledger_state["cost"] != pool_creation_data.pool_cost:
        errors_list.append(
            "'cost' value is different than expected; "
            f"Expected: {pool_creation_data.pool_cost} vs Returned: {pool_ledger_state['cost']}"
        )

    if pool_ledger_state["margin"] != pool_creation_data.pool_margin:
        errors_list.append(
            "'margin' value is different than expected; "
            f"Expected: {pool_creation_data.pool_margin} vs Returned: {pool_ledger_state['margin']}"
        )

    if pool_ledger_state["pledge"] != pool_creation_data.pool_pledge:
        errors_list.append(
            "'pledge' value is different than expected; "
            f"Expected: {pool_creation_data.pool_pledge} vs Returned: {pool_ledger_state['pledge']}"
        )

    if pool_ledger_state["relays"] != (pool_creation_data.pool_relay_dns or []):
        errors_list.append(
            "'relays' value is different than expected; "
            f"Expected: {pool_creation_data.pool_relay_dns} vs "
            f"Returned: {pool_ledger_state['relays']}"
        )

    if pool_creation_data.pool_metadata_url and pool_creation_data.pool_metadata_hash:
        metadata = pool_ledger_state.get("metadata") or {}

        metadata_hash = metadata.get("hash")
        if metadata_hash != pool_creation_data.pool_metadata_hash:
            errors_list.append(
                "'metadata hash' value is different than expected; "
                f"Expected: {pool_creation_data.pool_metadata_hash} vs "
                f"Returned: {metadata_hash}"
            )

        metadata_url = metadata.get("url")
        if metadata_url != pool_creation_data.pool_metadata_url:
            errors_list.append(
                "'metadata url' value is different than expected; "
                f"Expected: {pool_creation_data.pool_metadata_url} vs "
                f"Returned: {metadata_url}"
            )
    elif pool_ledger_state["metadata"] is not None:
        errors_list.append(
            "'metadata' value is different than expected; "
            f"Expected: None vs Returned: {pool_ledger_state['metadata']}"
        )

    if errors_list:
        for err in errors_list:
            LOGGER.error(err)
        LOGGER.error(f"Stake Pool Details: \n{pool_ledger_state}")

    return "\n\n".join(errors_list)
