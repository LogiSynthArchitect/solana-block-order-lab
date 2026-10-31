"""
Validator Registry for Solana Block Order Lab.
Tracks target validators across Agave v2.0+, Jito-Solana v2.0+, and Frankendancer/Firedancer.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ClientFamily(str, Enum):
    """Solana validator client architecture families."""
    AGAVE = "agave"
    JITO = "jito"
    FIREDANCER = "firedancer"
    UNKNOWN = "unknown"


class ValidatorIdentity(BaseModel):
    """Metadata describing a Solana validator node and its execution client."""
    vote_pubkey: str = Field(..., description="Validator vote account public key.")
    identity_pubkey: str = Field(..., description="Validator node identity (signing) public key.")
    client_family: ClientFamily = Field(
        default=ClientFamily.UNKNOWN,
        description="Identified validator client family.",
    )
    client_version: Optional[str] = Field(
        default=None,
        description="Software version string reported by cluster nodes (e.g. '2.0.14').",
    )
    name: str = Field(default="", description="Human-readable node label or operator.")
    commission: int = Field(default=0, description="Fee commission percentage.")
    activated_stake_lamports: int = Field(default=0, description="Active stake in lamports.")


# Curated catalog of benchmark mainnet validators across the 3 client architectures
KNOWN_VALIDATORS: List[ValidatorIdentity] = [
    # Agave v2.0+ Validators
    ValidatorIdentity(
        vote_pubkey="CertusDeBWSi8AHv5j1y7rZ2sK4Xgq8f9Q2Nq6m5rC4C",
        identity_pubkey="CertusDeBWSi8AHv5j1y7rZ2sK4Xgq8f9Q2Nq6m5rC4C",
        client_family=ClientFamily.AGAVE,
        client_version="2.0.15",
        name="Certus One (Agave Reference)",
    ),
    ValidatorIdentity(
        vote_pubkey="ChorusMMK7i1khqe7zQpx9KzGge85tEw2vJ7nZqJ9P8f",
        identity_pubkey="ChorusMMK7i1khqe7zQpx9KzGge85tEw2vJ7nZqJ9P8f",
        client_family=ClientFamily.AGAVE,
        client_version="2.0.12",
        name="Chorus One (Agave Mainnet)",
    ),
    # Jito-Solana v2.0+ (Mempool-less bundle block builder)
    ValidatorIdentity(
        vote_pubkey="J1to111111111111111111111111111111111111111",
        identity_pubkey="Jito444444444444444444444444444444444444444",
        client_family=ClientFamily.JITO,
        client_version="2.0.14-jito",
        name="Jito Foundation Validator",
    ),
    ValidatorIdentity(
        vote_pubkey="StakeBQ1b3p9K751xZ9P6R58xL9pZ4v8m5j1y7rZ2sK4",
        identity_pubkey="StakeBQ1b3p9K751xZ9P6R58xL9pZ4v8m5j1y7rZ2sK4",
        client_family=ClientFamily.JITO,
        client_version="2.0.15-jito",
        name="Stakefish (Jito-Solana)",
    ),
    # Frankendancer / Firedancer (Jump Crypto C/C++ runtime)
    ValidatorIdentity(
        vote_pubkey="Fdnc111111111111111111111111111111111111111",
        identity_pubkey="Fdnc444444444444444444444444444444444444444",
        client_family=ClientFamily.FIREDANCER,
        client_version="0.114.10204 (frankendancer)",
        name="Jump Firedancer Canary",
    ),
    ValidatorIdentity(
        vote_pubkey="F1re111111111111111111111111111111111111111",
        identity_pubkey="F1re444444444444444444444444444444444444444",
        client_family=ClientFamily.FIREDANCER,
        client_version="0.200.20000 (firedancer)",
        name="Jump Firedancer Testnet Primary",
    ),
]


class ValidatorRegistry:
    """Registry managing target validators and client classification logic."""

    def __init__(self, validators: Optional[List[ValidatorIdentity]] = None):
        self._validators: Dict[str, ValidatorIdentity] = {}
        initial = validators or KNOWN_VALIDATORS
        for v in initial:
            self.register(v)

    def register(self, validator: ValidatorIdentity) -> None:
        """Register or update a validator identity in the registry."""
        self._validators[validator.identity_pubkey] = validator

    def get(self, identity_pubkey: str) -> Optional[ValidatorIdentity]:
        """Fetch validator metadata by identity pubkey."""
        return self._validators.get(identity_pubkey)

    def get_by_family(self, family: ClientFamily) -> List[ValidatorIdentity]:
        """Retrieve all registered validators belonging to a specific client family."""
        return [v for v in self._validators.values() if v.client_family == family]

    def all_validators(self) -> List[ValidatorIdentity]:
        """Retrieve list of all registered validators."""
        return list(self._validators.values())

    @staticmethod
    def classify_client(version_string: Optional[str]) -> ClientFamily:
        """
        Classify client family from an RPC version string or software descriptor.
        Examples:
            '2.0.14-jito' -> JITO
            '0.114.10204' / 'frankendancer' / 'firedancer' -> FIREDANCER
            '2.0.15' / 'agave' -> AGAVE
        """
        if not version_string:
            return ClientFamily.UNKNOWN

        v_lower = version_string.lower()
        if "firedancer" in v_lower or "frankendancer" in v_lower or v_lower.startswith("0."):
            return ClientFamily.FIREDANCER
        if "jito" in v_lower:
            return ClientFamily.JITO
        if "agave" in v_lower or v_lower.startswith("2.") or v_lower.startswith("1.18"):
            return ClientFamily.AGAVE

        return ClientFamily.UNKNOWN
