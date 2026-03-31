# NLRB Tables Schema

This diagram shows the database schema for NLRB R Cases and C Cases, consolidated from three filing systems: NxGen, CATS, and CHIPS.

## Entity Relationship Diagram

```mermaid
erDiagram
    R_CASES ||--o{ ELECTIONS : ""
    R_CASES ||--|| R_CASES_ADDRESS : ""
    C_CASES ||--|| C_CASES_ADDRESS : ""
    
    R_CASES {
        string r_case_number
        string type
        date date_filed
        date date_closed
        string filing_system
    }
    
    R_CASES_ADDRESS {
        string r_case_number
        string company_name
        string state
        string city
        string zip_code
        string filing_system
    }
    
    ELECTIONS {
        string r_case_number
        string unit
        date election_date
        string election_result
        string union_won
        float pct_votes_for
        float union_representation
        string filing_system
    }
    
    C_CASES {
        string c_case_number
        string type
        date date_filed
        string allegations
        string merit
        string filing_system
    }
    
    C_CASES_ADDRESS {
        string c_case_number
        string company_name
        string state
        string city
        string zip_code
        string filing_system
    }
```

## Relationships

- **R_CASES to ELECTIONS**: One-to-many (one R case can have multiple elections in different units)
- **R_CASES to R_CASES_ADDRESS**: One-to-one (each R case has one address record)
- **C_CASES to C_CASES_ADDRESS**: One-to-one (each C case has one address record)

## Key Fields

- R-related tables are linked via the `r_case_number` field
- C-related tables are linked via the `c_case_number` field
