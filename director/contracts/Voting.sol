// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// Majority voting over a single pending order.
///
/// The contract is deployed with the list of allowed voter addresses
/// (their number must be odd). Each allowed address can vote exactly
/// once, either to approve or to reject. As soon as one side reaches
/// the majority (n / 2 + 1), voting is finished and every further vote
/// is rejected with "Voting ended.".
contract Voting {
    mapping(address => bool) public isVoter;
    mapping(address => bool) public hasVoted;

    uint256 public voterCount;
    uint256 public approveCount;
    uint256 public rejectCount;

    bool public finished;
    bool public accepted;

    constructor(address[] memory voters) {
        require(voters.length % 2 == 1, "Even number of voters.");

        for (uint256 i = 0; i < voters.length; i++) {
            isVoter[voters[i]] = true;
        }
        voterCount = voters.length;
    }

    function vote(bool approve) external {
        require(isVoter[msg.sender], "Invalid address.");
        require(!finished, "Voting ended.");
        require(!hasVoted[msg.sender], "Already voted.");

        hasVoted[msg.sender] = true;

        if (approve) {
            approveCount++;
        } else {
            rejectCount++;
        }

        uint256 majority = voterCount / 2 + 1;
        if (approveCount >= majority) {
            finished = true;
            accepted = true;
        } else if (rejectCount >= majority) {
            finished = true;
            accepted = false;
        }
    }
}
