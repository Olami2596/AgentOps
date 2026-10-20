
# AgentOps Project Checklist

## Phase 1 — Requirements and Design

- [X] Confirm MVP decisions
- [X] Define requirements and acceptance criteria
- [X] Define architecture and security boundaries
- [X] Design initial database entities and relationships

## Phase 2 — Clean Project Setup

- [X] Create separate AgentOps directory
- [X] Initialize project with uv
- [X] Create isolated Python environment
- [X] Correct and verify project configuration
- [X] Improve Git ignore rules
- [X] Verify the project entry point
- [X] Finalize initial project structure

## Phase 3 — Database and Workflow Registry

- [ ] Design the final SQLite schema
- [ ] Implement database initialization
- [ ] Implement workflow registry operations
- [ ] Test workflow discovery and retrieval

## Phase 4 — Workflow Execution

- [ ] Implement order validation
- [ ] Implement execution tracking
- [ ] Record processing results and errors
- [ ] Prevent duplicate imports
- [ ] Test partial failures and recovery

## Phase 5 — MCP Integration

- [ ] Verify installed SDK patterns
- [ ] Implement AgentOps MCP tools
- [ ] Test MCP client/server communication

## Phase 6 — Backend and Browser Interface

- [ ] Implement FastAPI backend
- [ ] Build Streamlit chat interface
- [ ] Connect the UI, backend, and MCP client
- [ ] Display execution history and failure details

## Phase 7 — Safety and Reliability

- [ ] Implement retry eligibility checks
- [ ] Enforce approval requirements
- [ ] Implement audit logging
- [ ] Test security and failure scenarios

## Phase 8 — Portfolio and Documentation

- [ ] Complete automated tests
- [ ] Demonstrate success, failure, and recovery
- [ ] Complete README and setup instructions
- [ ] Document architecture and limitations
