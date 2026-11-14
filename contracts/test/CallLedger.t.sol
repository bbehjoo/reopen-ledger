// SPDX-License-Identifier: Apache-2.0
pragma solidity 0.8.28;

import {CallLedger} from "../src/CallLedger.sol";

/// Foundry cheatcodes used here (no library dependency).
interface Vm {
    struct Log {
        bytes32[] topics;
        bytes data;
        address emitter;
    }

    function recordLogs() external;
    function getRecordedLogs() external returns (Log[] memory);
    function prank(address) external;
    function deal(address, uint256) external;
    function load(address, bytes32) external view returns (bytes32);
}

contract CallLedgerTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 constant COMMITTED = keccak256("Committed(address,uint32,uint16,bytes)");
    CallLedger ledger;

    function setUp() public {
        ledger = new CallLedger();
    }

    function _one(Vm.Log[] memory logs) internal pure returns (Vm.Log memory) {
        require(logs.length == 1, "want one log");
        return logs[0];
    }

    function testCommitEmitsTheRecord() public {
        address who = address(0xBEEF);
        bytes memory payload = hex"b20000000000000000000078ee7ce2fe4908108c1388";
        vm.recordLogs();
        vm.prank(who);
        ledger.commit(120261113, 1, payload);
        Vm.Log memory l = _one(vm.getRecordedLogs());
        require(l.emitter == address(ledger), "emitter");
        require(l.topics.length == 4, "topics");
        require(l.topics[0] == COMMITTED, "topic0");
        require(l.topics[1] == bytes32(uint256(uint160(who))), "committer");
        require(l.topics[2] == bytes32(uint256(120261113)), "window");
        require(l.topics[3] == bytes32(uint256(1)), "schema");
        require(keccak256(abi.decode(l.data, (bytes))) == keccak256(payload), "data");
    }

    function testTrailingAttributionSuffixIsIgnored() public {
        // ERC-8021-style suffix: codes, length byte, schema byte, 16-byte marker
        bytes memory suffix = abi.encodePacked("bc_test1", uint8(8), uint8(0), hex"80218021802180218021802180218021");
        bytes memory payload = hex"01";
        bytes memory cd = abi.encodePacked(abi.encodeCall(CallLedger.commit, (220261113, 3, payload)), suffix);
        vm.recordLogs();
        (bool ok,) = address(ledger).call(cd);
        require(ok, "call with suffix failed");
        Vm.Log memory l = _one(vm.getRecordedLogs());
        require(l.topics[2] == bytes32(uint256(220261113)), "window");
        require(keccak256(abi.decode(l.data, (bytes))) == keccak256(payload), "data unchanged");
    }

    function testCommitManyEmitsOneEventEach() public {
        uint32[] memory w = new uint32[](3);
        uint16[] memory s = new uint16[](3);
        bytes[] memory d = new bytes[](3);
        for (uint256 i; i < 3; ++i) {
            w[i] = uint32(120261113 + i);
            s[i] = uint16(1 + i);
            d[i] = abi.encodePacked(uint8(i));
        }
        vm.recordLogs();
        ledger.commitMany(w, s, d);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        require(logs.length == 3, "three logs");
        for (uint256 i; i < 3; ++i) {
            require(logs[i].topics[2] == bytes32(uint256(w[i])), "window i");
            require(logs[i].topics[3] == bytes32(uint256(s[i])), "schema i");
        }
    }

    function testCommitManyLengthMismatchReverts() public {
        uint32[] memory w = new uint32[](2);
        uint16[] memory s = new uint16[](1);
        bytes[] memory d = new bytes[](2);
        (bool ok, bytes memory ret) =
            address(ledger).call(abi.encodeCall(CallLedger.commitMany, (w, s, d)));
        require(!ok, "should revert");
        require(bytes4(ret) == CallLedger.LengthMismatch.selector, "error selector");
    }

    function testCannotReceiveFunds() public {
        vm.deal(address(this), 1 ether);
        (bool ok,) = address(ledger).call{value: 1}("");
        require(!ok, "plain transfer accepted");
        (ok,) = address(ledger).call{value: 1}(abi.encodeCall(CallLedger.commit, (1, 1, hex"")));
        require(!ok, "value with commit accepted");
        require(address(ledger).balance == 0, "balance");
    }

    function testStoresNothing() public {
        ledger.commit(1, 1, hex"ff");
        for (uint256 slot; slot < 4; ++slot) {
            require(vm.load(address(ledger), bytes32(slot)) == bytes32(0), "storage written");
        }
    }

    function testFuzzAnyCommitterAnyRecord(address who, uint32 w, uint16 s, bytes calldata d) public {
        vm.recordLogs();
        vm.prank(who);
        ledger.commit(w, s, d);
        Vm.Log memory l = _one(vm.getRecordedLogs());
        require(l.topics[1] == bytes32(uint256(uint160(who))), "committer");
        require(keccak256(abi.decode(l.data, (bytes))) == keccak256(d), "data");
    }
}
