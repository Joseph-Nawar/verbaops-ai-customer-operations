# VerbaOps AI Conceptual Data Model

This Phase 0 model defines ownership, scope, and relationships rather than a physical schema. Most VerbaOps AI domain and AI records are tenant-scoped. NovaCommerce commerce data is conceptually owned by the Commerce Sandbox/API even if future local development shares infrastructure.

## Mermaid ERD

```mermaid
erDiagram
    TENANTS ||--o{ USERS : has
    TENANTS ||--o{ CUSTOMERS : owns
    USERS o|--o| CUSTOMERS : maps_to
    TENANTS ||--o{ PRODUCTS : catalogs
    TENANTS ||--o{ ORDERS : owns
    CUSTOMERS ||--o{ ORDERS : places
    ORDERS ||--|{ ORDER_ITEMS : contains
    PRODUCTS ||--o{ ORDER_ITEMS : referenced_by
    ORDERS ||--o{ SHIPMENTS : has
    ORDERS ||--o{ REFUNDS : has
    ORDERS ||--o{ RETURNS : has
    RETURNS ||--|{ RETURN_ITEMS : contains
    ORDER_ITEMS ||--o{ RETURN_ITEMS : returned_as
    TENANTS ||--o{ DELIVERY_SLOTS : offers
    ORDERS o|--o{ SUPPORT_TICKETS : concerns
    CUSTOMERS ||--o{ SUPPORT_TICKETS : opens
    TENANTS ||--o{ CONVERSATIONS : scopes
    USERS ||--o{ CONVERSATIONS : participates
    CUSTOMERS o|--o{ CONVERSATIONS : maps_to
    CONVERSATIONS ||--|{ MESSAGES : contains
    CONVERSATIONS ||--o{ AGENT_RUNS : has
    AGENT_RUNS ||--o{ TOOL_INVOCATIONS : proposes
    AGENT_RUNS ||--o{ APPROVAL_REQUESTS : may_create
    USERS o|--o{ APPROVAL_REQUESTS : reviews
    TENANTS ||--o{ KNOWLEDGE_DOCUMENTS : owns
    KNOWLEDGE_DOCUMENTS ||--|{ KNOWLEDGE_VERSIONS : versions
    KNOWLEDGE_VERSIONS ||--|{ KNOWLEDGE_CHUNKS : chunks
    TENANTS ||--o{ EVAL_CASES : owns
    EVAL_CASES ||--o{ EVAL_RESULTS : assessed_by
    EVAL_RUNS ||--|{ EVAL_RESULTS : produces
    TENANTS ||--o{ EVAL_RUNS : owns
    TENANTS ||--o{ AUDIT_EVENTS : scopes
    USERS o|--o{ AUDIT_EVENTS : causes
    AGENT_RUNS o|--o{ AUDIT_EVENTS : correlates

    TENANTS {
        uuid id PK
        string name
    }
    USERS {
        uuid id PK
        uuid tenant_id FK
        string principal_ref
    }
    CUSTOMERS {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string commerce_ref
    }
    PRODUCTS {
        uuid id PK
        uuid tenant_id FK
        string commerce_ref
    }
    ORDERS {
        uuid id PK
        uuid tenant_id FK
        uuid customer_id FK
        string commerce_ref
    }
    ORDER_ITEMS {
        uuid id PK
        uuid order_id FK
        uuid product_id FK
    }
    SHIPMENTS {
        uuid id PK
        uuid order_id FK
        string status
    }
    REFUNDS {
        uuid id PK
        uuid order_id FK
        string status
    }
    RETURNS {
        uuid id PK
        uuid order_id FK
        string status
    }
    RETURN_ITEMS {
        uuid id PK
        uuid return_id FK
        uuid order_item_id FK
    }
    DELIVERY_SLOTS {
        uuid id PK
        uuid tenant_id FK
        string status
    }
    SUPPORT_TICKETS {
        uuid id PK
        uuid tenant_id FK
        uuid customer_id FK
        uuid order_id FK
        string status
    }
    CONVERSATIONS {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        uuid customer_id FK
    }
    MESSAGES {
        uuid id PK
        uuid conversation_id FK
        string role
    }
    AGENT_RUNS {
        uuid id PK
        uuid conversation_id FK
        string status
    }
    TOOL_INVOCATIONS {
        uuid id PK
        uuid agent_run_id FK
        string tool_name
    }
    APPROVAL_REQUESTS {
        uuid id PK
        uuid agent_run_id FK
        uuid reviewer_id FK
        string status
    }
    KNOWLEDGE_DOCUMENTS {
        uuid id PK
        uuid tenant_id FK
        string title
    }
    KNOWLEDGE_VERSIONS {
        uuid id PK
        uuid document_id FK
        string version
    }
    KNOWLEDGE_CHUNKS {
        uuid id PK
        uuid version_id FK
        string locator
    }
    EVAL_CASES {
        uuid id PK
        uuid tenant_id FK
        string version
    }
    EVAL_RUNS {
        uuid id PK
        uuid tenant_id FK
        string version
    }
    EVAL_RESULTS {
        uuid id PK
        uuid eval_case_id FK
        uuid eval_run_id FK
    }
    AUDIT_EVENTS {
        uuid id PK
        uuid tenant_id FK
        uuid actor_user_id FK
        uuid agent_run_id FK
        string event_type
    }
```

## Entity explanations

- **tenants** are the isolation boundary. NovaCommerce is one tenant in the demo; the platform model remains reusable.
- **users** are authenticated principals with roles and trusted tenant context. **customers** are commerce-domain records; a user may map to a customer.
- **products**, **orders**, and **order_items** describe commerce concepts. A customer owns orders, and an order contains items.
- **shipments**, **refunds**, and **returns** hold order-related state. **return_items** identifies the order items included in a return. **delivery_slots** represents available delivery choices.
- **support_tickets** records customer support work and may reference zero or one order; the conceptual `order_id` is nullable when a ticket is not tied to a specific order.
- **conversations**, **messages**, and **agent_runs** represent durable interaction history. A conversation owns messages and agent runs.
- **tool_invocations** records typed proposals and calls owned by an agent run. **approval_requests** captures human decisions for high-risk actions; approval is bound to the exact proposal. A pending approval request may have no reviewer, so the conceptual `reviewer_id` is nullable until the request is claimed or decided by an authorized reviewer.
- **knowledge_documents**, **knowledge_versions**, and **knowledge_chunks** provide versioned retrieval evidence. Retrieved text is evidence, not trusted instructions.
- **eval_cases**, **eval_runs**, and **eval_results** support versioned evaluation. Results reference both the evaluated case and the run/version context.
- **audit_events** capture security- and business-sensitive events with trusted actor and correlation references.

The logical data model does not grant the Agent Runtime direct table access to NovaCommerce data. Commerce reads and writes cross the authenticated Commerce Sandbox/API boundary.
