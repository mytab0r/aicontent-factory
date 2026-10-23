// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
contract TestUSDT {
  string public name = "Tether USD"; string public symbol = "USDT"; uint8 public decimals = 6;
  uint256 public totalSupply; mapping(address=>uint256) public balanceOf; mapping(address=>mapping(address=>uint256)) public allowance;
  event Transfer(address indexed from, address indexed to, uint256 value);
  event Approval(address indexed owner, address indexed spender, uint256 value);
  constructor(uint256 s){ totalSupply=s; balanceOf[msg.sender]=s; emit Transfer(address(0),msg.sender,s); }
  function transfer(address to,uint256 v) external returns(bool){ return _t(msg.sender,to,v); }
  function approve(address sp,uint256 v) external returns(bool){ allowance[msg.sender][sp]=v; emit Approval(msg.sender,sp,v); return true; }
  function transferFrom(address f,address to,uint256 v) external returns(bool){ allowance[f][msg.sender]-=v; return _t(f,to,v); }
  function _t(address f,address to,uint256 v) internal returns(bool){ balanceOf[f]-=v; balanceOf[to]+=v; emit Transfer(f,to,v); return true; }
}
