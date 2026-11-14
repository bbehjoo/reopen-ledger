// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.28;

/// @title CallLedger
/// @notice An append-only public record. `commit` emits one event and stores nothing.
///         No owner, no admin, no upgrade path, no storage, no payable function: the contract can hold no
///         funds and nobody can change it. Bytes appended after the ABI arguments (ERC-8021 attribution
///         suffixes) are ignored, so a caller's Builder Code rides along without affecting the record.
///         What `data` means is set by `schemaId` (METHODS.md section 4); the contract never reads it.
contract CallLedger {
    /// @param committer msg.sender: the wallet (or smart account) whose record this is
    /// @param windowId  the window the data is about: kind * 100000000 + yyyymmdd (METHODS.md section 3)
    /// @param schemaId  the encoding of `data` (1 = probability calls, 2 = coverage call, 3 = daily anchor)
    /// @param data      the record itself
    event Committed(address indexed committer, uint32 indexed windowId, uint16 indexed schemaId, bytes data);

    error LengthMismatch();

    /// @notice Record `data` for one window under one schema.
    function commit(uint32 windowId, uint16 schemaId, bytes calldata data) external {
        emit Committed(msg.sender, windowId, schemaId, data);
    }

    /// @notice Several records in one transaction (one event each, same committer).
    function commitMany(uint32[] calldata windowIds, uint16[] calldata schemaIds, bytes[] calldata data)
        external
    {
        uint256 n = windowIds.length;
        if (schemaIds.length != n || data.length != n) revert LengthMismatch();
        for (uint256 i; i < n; ++i) {
            emit Committed(msg.sender, windowIds[i], schemaIds[i], data[i]);
        }
    }
}
