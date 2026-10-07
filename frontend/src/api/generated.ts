// Generated from FastAPI OpenAPI by scripts/api-types.mjs. DO NOT EDIT.
export interface paths {
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/agent/research": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Research */
        post: operations["research_v1_agent_research_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/reports/equity-research": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Equity Research */
        post: operations["equity_research_v1_reports_equity_research_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/research/company-snapshot": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Company Snapshot */
        post: operations["company_snapshot_v1_research_company_snapshot_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/research/compare-periods": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Period Comparison */
        post: operations["period_comparison_v1_research_compare_periods_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/research/fundamental-trends": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Fundamental Trends */
        post: operations["fundamental_trends_v1_research_fundamental_trends_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/research/market-behavior": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Market Behavior */
        post: operations["market_behavior_v1_research_market_behavior_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/research/quality": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Research Quality */
        post: operations["research_quality_v1_research_quality_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AgentExecutionTrace */
        AgentExecutionTrace: {
            /** Steps */
            steps: components["schemas"]["AgentTraceStep"][];
        };
        /**
         * AgentIntent
         * @enum {string}
         */
        AgentIntent: "COMPANY_OVERVIEW" | "FUNDAMENTAL_FOCUS" | "MARKET_FOCUS" | "QUALITY_FOCUS" | "BROAD_RESEARCH";
        /** AgentPlan */
        AgentPlan: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            intent: components["schemas"]["AgentIntent"];
            /**
             * Plan Version
             * @constant
             */
            plan_version: "1.0";
            reason_code: components["schemas"]["AgentReasonCode"];
            /** Requested Focus */
            requested_focus: components["schemas"]["ClaimSection"][] | null;
            /** Selected Skill Id */
            selected_skill_id: string;
            /** Ticker */
            ticker: string;
        };
        /**
         * AgentReasonCode
         * @enum {string}
         */
        AgentReasonCode: "COMPANY_INFORMATION_REQUEST" | "FUNDAMENTAL_ANALYSIS_REQUEST" | "MARKET_ANALYSIS_REQUEST" | "DATA_QUALITY_REQUEST" | "BROAD_EQUITY_RESEARCH_REQUEST";
        /** AgentResearchEnvelope */
        AgentResearchEnvelope: {
            data: components["schemas"]["GroundedResearchAnswer"];
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Limitations */
            limitations: string[];
            quality: components["schemas"]["QualityReport"];
            /**
             * Request Id
             * Format: uuid4
             */
            request_id: string;
            /**
             * Schema Version
             * @default 1.0
             * @constant
             */
            schema_version: "1.0";
        };
        /** AgentResearchRequest */
        AgentResearchRequest: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /** Question */
            question: string;
            /** @default AUTO */
            response_language: components["schemas"]["ResponseLanguage"];
            /** Ticker */
            ticker: string;
        };
        /**
         * AgentStatus
         * @enum {string}
         */
        AgentStatus: "COMPLETED" | "COMPLETED_WITH_WARNINGS" | "BLOCKED" | "FAILED";
        /**
         * AgentTraceAction
         * @enum {string}
         */
        AgentTraceAction: "PLAN_REQUEST" | "PLAN_VALIDATED" | "SKILL_EXECUTION" | "READINESS_GATE" | "EVIDENCE_PROJECTION" | "SYNTHESIS_REQUEST" | "GROUNDING_VALIDATION" | "RESPONSE_RENDERED";
        /** AgentTraceStep */
        AgentTraceStep: {
            action: components["schemas"]["AgentTraceAction"];
            /** Duration Ms */
            duration_ms?: number | null;
            /** Error Code */
            error_code?: string | null;
            /** Sequence */
            sequence: number;
            /**
             * Status
             * @enum {string}
             */
            status: "SUCCESS" | "REPAIR_REQUIRED" | "BLOCKED" | "FAILED";
            /** Target */
            target: string;
        };
        /** CalculationAppendixEntry */
        CalculationAppendixEntry: {
            /** Canonical Id */
            canonical_id: string;
            /** Date */
            date: string | null;
            display_alias: components["schemas"]["CalculationDisplayAlias"];
            /** Input Display Aliases */
            input_display_aliases: components["schemas"]["EvidenceDisplayAlias"][];
            /** Period End */
            period_end: string | null;
            /** Period Start */
            period_start: string | null;
            provenance: components["schemas"]["CalculationProvenance"];
            /** Result */
            result: string | null;
            /** Result Unit */
            result_unit: string | null;
        };
        CalculationDisplayAlias: string;
        /** CalculationParameter */
        CalculationParameter: {
            /** Name */
            name: string;
            /** Value */
            value: string | number | boolean;
        };
        /** CalculationProvenance */
        CalculationProvenance: {
            /** Calculation Name */
            calculation_name: string;
            /** Evidence Id */
            evidence_id: string;
            /** Formula */
            formula: string;
            /** Input Evidence Ids */
            input_evidence_ids: string[];
            /**
             * Parameters
             * @default []
             */
            parameters: components["schemas"]["CalculationParameter"][];
        };
        /**
         * ClaimSection
         * @enum {string}
         */
        ClaimSection: "COMPANY" | "FUNDAMENTALS" | "MARKET" | "QUALITY";
        /**
         * ClaimType
         * @enum {string}
         */
        ClaimType: "SOURCE_FACT" | "COMPUTED_FACT" | "INTERPRETATION";
        /** CompanyProfile */
        CompanyProfile: {
            /** Cik */
            cik: string;
            /** Company Name */
            company_name: string;
            /** Currency */
            currency?: string | null;
            /** Exchange */
            exchange: string;
            provenance: components["schemas"]["ProvenanceRecord"];
            /** Ticker */
            ticker: string;
        };
        /** CompanySnapshotResult */
        CompanySnapshotResult: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /**
             * Calculation Provenance
             * @default []
             */
            calculation_provenance: components["schemas"]["CalculationProvenance"][];
            company: components["schemas"]["CompanyProfile"];
            /**
             * Evidence
             * @default []
             */
            evidence: components["schemas"]["EvidenceReference"][];
            /** Fundamentals */
            fundamentals: components["schemas"]["MetricSnapshot"][];
            /** Latest Close */
            latest_close?: number | null;
            latest_market_features: components["schemas"]["LatestMarketFeatures"];
            /** Latest Market Session */
            latest_market_session?: string | null;
            /**
             * Limitations
             * @default []
             */
            limitations: string[];
            /** Market Windows */
            market_windows: components["schemas"]["MarketWindowSummary"][];
            quality: components["schemas"]["QualityReport"];
            /** Ticker */
            ticker: string;
        };
        /** ComparePeriodsRequest */
        ComparePeriodsRequest: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /** @default latest_vs_prior_year_comparable */
            comparison: components["schemas"]["ComparisonSpec"];
            /** Metric */
            metric: string;
            /** Ticker */
            ticker: string;
        };
        /**
         * ComparisonSpec
         * @enum {string}
         */
        ComparisonSpec: "latest_vs_prior_year_comparable";
        /**
         * ComparisonType
         * @enum {string}
         */
        ComparisonType: "YEAR_OVER_YEAR";
        /** EquityResearchReportRequest */
        EquityResearchReportRequest: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /** @default ENGLISH */
            response_language: components["schemas"]["ReportLanguage"];
            /** Ticker */
            ticker: string;
        };
        /** EquityResearchReportResponse */
        EquityResearchReportResponse: {
            manifest_summary: components["schemas"]["ReportManifest"];
            /** Markdown */
            markdown: string;
            report: components["schemas"]["ResearchReport"];
        };
        /** ErrorResponse */
        ErrorResponse: {
            /** Error Code */
            error_code: string;
            /** Message */
            message: string;
            /**
             * Request Id
             * Format: uuid4
             */
            request_id: string;
        };
        /** EvidenceAppendixEntry */
        EvidenceAppendixEntry: {
            /** Canonical Id */
            canonical_id: string;
            display_alias: components["schemas"]["EvidenceDisplayAlias"];
            evidence: components["schemas"]["EvidenceReference"];
        };
        EvidenceDisplayAlias: string;
        /**
         * EvidenceKind
         * @enum {string}
         */
        EvidenceKind: "SOURCE_FACT" | "COMPUTATION";
        /** EvidenceReference */
        EvidenceReference: {
            /** Available Date */
            available_date?: string | null;
            /** Data Vintage */
            data_vintage?: string | null;
            /** Date */
            date?: string | null;
            /** Evidence Id */
            evidence_id: string;
            /** Filed At */
            filed_at?: string | null;
            kind: components["schemas"]["EvidenceKind"];
            /** Metric */
            metric: string;
            /** Period End */
            period_end?: string | null;
            /** Period Start */
            period_start?: string | null;
            /** Provider */
            provider: string;
            /** Source Reference */
            source_reference: string;
            /**
             * Transformation
             * @default []
             */
            transformation: string[];
            /** Unit */
            unit?: string | null;
            /** Value */
            value?: string | null;
        };
        /** FiscalPeriod */
        FiscalPeriod: {
            /** Fiscal Quarter */
            fiscal_quarter?: number | null;
            /** Fiscal Year */
            fiscal_year: number;
            frequency: components["schemas"]["PeriodFrequency"];
            /** Source Reference */
            source_reference: string;
        };
        /** FundamentalObservation */
        FundamentalObservation: {
            /** Accession Number */
            accession_number: string;
            /**
             * Available Date
             * Format: date
             */
            available_date: string;
            /** Data Vintage */
            data_vintage: string;
            /**
             * Filed At
             * Format: date
             */
            filed_at: string;
            fiscal_period?: components["schemas"]["FiscalPeriod"] | null;
            /** Form */
            form: string;
            /** Metric */
            metric: string;
            /**
             * Period End
             * Format: date
             */
            period_end: string;
            /** Period Start */
            period_start?: string | null;
            /** Provider */
            provider: string;
            /**
             * Retrieved At
             * Format: date-time
             */
            retrieved_at: string;
            /** Source Reference */
            source_reference: string;
            /** Ticker */
            ticker: string;
            /**
             * Transformation
             * @default []
             */
            transformation: string[];
            /** Unit */
            unit: string;
            /** Value */
            value: string;
        };
        /** FundamentalTrendResult */
        FundamentalTrendResult: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /**
             * Calculation Provenance
             * @default []
             */
            calculation_provenance: components["schemas"]["CalculationProvenance"][];
            /**
             * Evidence
             * @default []
             */
            evidence: components["schemas"]["EvidenceReference"][];
            /**
             * Limitations
             * @default []
             */
            limitations: string[];
            /** Metrics */
            metrics: components["schemas"]["MetricTrendResult"][];
            quality: components["schemas"]["QualityReport"];
            /** Ticker */
            ticker: string;
        };
        /** FundamentalTrendsRequest */
        FundamentalTrendsRequest: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /** Metrics */
            metrics?: string[] | null;
            /** Ticker */
            ticker: string;
        };
        /** GroundedClaim */
        GroundedClaim: {
            /** Claim Id */
            claim_id: string;
            claim_type: components["schemas"]["ClaimType"];
            /** Evidence Ids */
            evidence_ids: string[];
            section: components["schemas"]["ClaimSection"];
            /** Statement */
            statement: string;
        };
        /** GroundedResearchAnswer */
        GroundedResearchAnswer: {
            agent_status: components["schemas"]["AgentStatus"];
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /** Calculation Provenance */
            calculation_provenance: components["schemas"]["CalculationProvenance"][];
            /** Citations */
            citations: {
                [key: string]: components["schemas"]["EvidenceReference"];
            };
            /** Claims */
            claims: components["schemas"]["GroundedClaim"][];
            /**
             * Language Fallback
             * @default false
             */
            language_fallback: boolean;
            /** Limitations */
            limitations: string[];
            /** Llm Usage */
            llm_usage: components["schemas"]["LLMUsageMetadata"][];
            plan: components["schemas"]["AgentPlan"];
            /** Planner Prompt Version */
            planner_prompt_version: string;
            quality: components["schemas"]["QualityReport"];
            /**
             * Rendered Answer
             * @default
             */
            rendered_answer: string;
            /**
             * Response Language
             * @default ENGLISH
             * @enum {string}
             */
            response_language: "ENGLISH" | "CHINESE";
            synthesis_payload_audit?: components["schemas"]["SynthesisPayloadAudit"] | null;
            /** Synthesis Prompt Version */
            synthesis_prompt_version: string;
            synthesis_readiness: components["schemas"]["SynthesisReadiness"];
            /** Ticker */
            ticker: string;
            trace: components["schemas"]["AgentExecutionTrace"];
            /**
             * Unavailable Context
             * @default []
             */
            unavailable_context: string[];
            /** Used Skill Ids */
            used_skill_ids: string[];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthResponse */
        HealthResponse: {
            /**
             * Service
             * @default financial-research-fde
             * @constant
             */
            service: "financial-research-fde";
            /**
             * Status
             * @default ok
             * @constant
             */
            status: "ok";
        };
        /**
         * LLMPhase
         * @enum {string}
         */
        LLMPhase: "PLANNING" | "PLANNING_REPAIR" | "SYNTHESIS" | "SYNTHESIS_REPAIR" | "SEMANTIC_JUDGE";
        /** LLMUsageMetadata */
        LLMUsageMetadata: {
            /** Input Tokens */
            input_tokens?: number | null;
            /** Latency Ms */
            latency_ms: number;
            /** Model */
            model: string;
            /** Output Tokens */
            output_tokens?: number | null;
            phase: components["schemas"]["LLMPhase"];
            /** Prompt Version */
            prompt_version: string;
            /** Provider */
            provider: string;
            /** Repair Count */
            repair_count: number;
            /** Success */
            success: boolean;
            /** Total Tokens */
            total_tokens?: number | null;
        };
        /** LatestMarketFeatures */
        LatestMarketFeatures: {
            /** Close To Sma 20 */
            close_to_sma_20?: number | null;
            /** Close To Sma 5 */
            close_to_sma_5?: number | null;
            /** Close To Sma 60 */
            close_to_sma_60?: number | null;
        };
        /** MarketBehaviorRequest */
        MarketBehaviorRequest: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /**
             * Lookback Sessions
             * @default 60
             */
            lookback_sessions: number;
            /** Ticker */
            ticker: string;
        };
        /** MarketBehaviorResult */
        MarketBehaviorResult: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /**
             * Calculation Provenance
             * @default []
             */
            calculation_provenance: components["schemas"]["CalculationProvenance"][];
            /**
             * Evidence
             * @default []
             */
            evidence: components["schemas"]["EvidenceReference"][];
            /** Latest Close */
            latest_close?: number | null;
            latest_market_features: components["schemas"]["LatestMarketFeatures"];
            /** Latest Market Session */
            latest_market_session?: string | null;
            /**
             * Limitations
             * @default []
             */
            limitations: string[];
            quality: components["schemas"]["QualityReport"];
            /** Ticker */
            ticker: string;
            window: components["schemas"]["MarketWindowSummary"];
        };
        /** MarketWindowSummary */
        MarketWindowSummary: {
            /**
             * Annualized
             * @default false
             * @constant
             */
            annualized: false;
            /** Cumulative Return */
            cumulative_return?: number | null;
            /**
             * Limitations
             * @default []
             */
            limitations: string[];
            /** Lookback Sessions Available */
            lookback_sessions_available: number;
            /** Lookback Sessions Requested */
            lookback_sessions_requested: number;
            /** Realized Volatility Daily */
            realized_volatility_daily?: number | null;
            status: components["schemas"]["ResultStatus"];
            volatility_status: components["schemas"]["ResultStatus"];
            /** Window High */
            window_high?: number | null;
            /** Window Low */
            window_low?: number | null;
        };
        /**
         * MetricKind
         * @enum {string}
         */
        MetricKind: "FLOW" | "STOCK";
        /** MetricSnapshot */
        MetricSnapshot: {
            /**
             * Limitations
             * @default []
             */
            limitations: string[];
            /** Metric */
            metric: string;
            metric_kind: components["schemas"]["MetricKind"];
            observation?: components["schemas"]["FundamentalObservation"] | null;
            status: components["schemas"]["ResultStatus"];
        };
        /** MetricTrendResult */
        MetricTrendResult: {
            /** Absolute Change */
            absolute_change?: string | null;
            /**
             * Calculation Provenance
             * @default []
             */
            calculation_provenance: components["schemas"]["CalculationProvenance"][];
            comparable_observation?: components["schemas"]["FundamentalObservation"] | null;
            comparison_status: components["schemas"]["ResultStatus"];
            /** @default YEAR_OVER_YEAR */
            comparison_type: components["schemas"]["ComparisonType"];
            current_observation?: components["schemas"]["FundamentalObservation"] | null;
            direction: components["schemas"]["TrendDirection"];
            /**
             * Evidence
             * @default []
             */
            evidence: components["schemas"]["EvidenceReference"][];
            /**
             * Limitations
             * @default []
             */
            limitations: string[];
            /** Metric */
            metric: string;
            metric_kind: components["schemas"]["MetricKind"];
            /** Percentage Change */
            percentage_change?: string | null;
            percentage_change_status: components["schemas"]["PercentageChangeStatus"];
        };
        /**
         * PercentageChangeStatus
         * @enum {string}
         */
        PercentageChangeStatus: "MEANINGFUL" | "NOT_MEANINGFUL" | "UNAVAILABLE";
        /** PeriodComparisonResult */
        PeriodComparisonResult: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /**
             * Calculation Provenance
             * @default []
             */
            calculation_provenance: components["schemas"]["CalculationProvenance"][];
            comparison_spec: components["schemas"]["ComparisonSpec"];
            /**
             * Evidence
             * @default []
             */
            evidence: components["schemas"]["EvidenceReference"][];
            /**
             * Limitations
             * @default []
             */
            limitations: string[];
            quality: components["schemas"]["QualityReport"];
            result: components["schemas"]["MetricTrendResult"];
            /** Ticker */
            ticker: string;
        };
        /**
         * PeriodFrequency
         * @enum {string}
         */
        PeriodFrequency: "QUARTERLY" | "ANNUAL";
        /** ProvenanceRecord */
        ProvenanceRecord: {
            /** Content Hash */
            content_hash?: string | null;
            /** Data Vintage */
            data_vintage: string;
            /** Provider */
            provider: string;
            /**
             * Retrieved At
             * Format: date-time
             */
            retrieved_at: string;
            /** Source Reference */
            source_reference: string;
            source_type: components["schemas"]["SourceType"];
            /**
             * Transformation
             * @default []
             */
            transformation: string[];
        };
        /** QualityIssue */
        QualityIssue: {
            /** Affected Context */
            affected_context?: string | null;
            /** Affected Date */
            affected_date?: string | null;
            /** Affected Field */
            affected_field?: string | null;
            /** Code */
            code: string;
            /** Message */
            message: string;
            severity: components["schemas"]["Severity"];
        };
        /** QualityReport */
        QualityReport: {
            /**
             * Issues
             * @default []
             */
            issues: components["schemas"]["QualityIssue"][];
            status: components["schemas"]["QualityStatus"];
        };
        /**
         * QualityStatus
         * @enum {string}
         */
        QualityStatus: "PASS" | "PASS_WITH_WARNINGS" | "FAIL";
        /** ReportFileHashes */
        ReportFileHashes: {
            "evidence.json": components["schemas"]["SHA256"];
            "report.json": components["schemas"]["SHA256"];
            "report.md": components["schemas"]["SHA256"];
        };
        ReportID: string;
        /** ReportIntegrity */
        ReportIntegrity: {
            /**
             * Algorithm
             * @default SHA-256
             * @constant
             */
            algorithm: "SHA-256";
            semantic_hash: components["schemas"]["SHA256"];
        };
        /** @enum {string} */
        ReportLanguage: "ENGLISH" | "CHINESE";
        /** ReportManifest */
        ReportManifest: {
            agent_status: components["schemas"]["AgentStatus"];
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /**
             * Bundle Version
             * @default research-report-bundle-v1
             * @constant
             */
            bundle_version: "research-report-bundle-v1";
            /** Calculation Count */
            calculation_count: number;
            /** Claim Count */
            claim_count: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Evidence Count */
            evidence_count: number;
            file_hashes?: components["schemas"]["ReportFileHashes"] | null;
            integrity: components["schemas"]["ReportIntegrity"];
            language: components["schemas"]["ReportLanguage"];
            /** Model */
            model: string;
            /**
             * Plan Version
             * @default deterministic-equity-report-plan-v1
             * @constant
             */
            plan_version: "deterministic-equity-report-plan-v1";
            /**
             * Planner Call Count
             * @default 0
             * @constant
             */
            planner_call_count: 0;
            /** Planner Prompt Version */
            planner_prompt_version?: null;
            /**
             * Planner Used
             * @default false
             * @constant
             */
            planner_used: false;
            /** Provider */
            provider: string;
            quality_status: components["schemas"]["QualityStatus"];
            /** Repair Count */
            repair_count: number;
            /**
             * Report Compiler Version
             * @default report-compiler-v1
             * @constant
             */
            report_compiler_version: "report-compiler-v1";
            report_id: components["schemas"]["ReportID"];
            report_status: components["schemas"]["ReportStatus"];
            /**
             * Report Version
             * @default research-report-v1
             * @constant
             */
            report_version: "research-report-v1";
            /**
             * Run Id
             * Format: uuid
             */
            run_id: string;
            /**
             * Selected Skill Id
             * @default equity_research
             * @constant
             */
            selected_skill_id: "equity_research";
            /** Synthesis Call Count */
            synthesis_call_count: number;
            /** Synthesis Prompt Version */
            synthesis_prompt_version: string;
            synthesis_readiness: components["schemas"]["SynthesisReadiness"];
            /** Ticker */
            ticker: string;
        };
        /** ReportRuntimeMetadata */
        ReportRuntimeMetadata: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Llm Usage */
            llm_usage: components["schemas"]["LLMUsageMetadata"][];
            /** Model */
            model: string;
            /**
             * Plan Version
             * @default deterministic-equity-report-plan-v1
             * @constant
             */
            plan_version: "deterministic-equity-report-plan-v1";
            /**
             * Planner Call Count
             * @default 0
             * @constant
             */
            planner_call_count: 0;
            /** Planner Prompt Version */
            planner_prompt_version?: null;
            /**
             * Planner Used
             * @default false
             * @constant
             */
            planner_used: false;
            /** Provider */
            provider: string;
            /** Repair Count */
            repair_count: number;
            /**
             * Report Compiler Version
             * @default report-compiler-v1
             * @constant
             */
            report_compiler_version: "report-compiler-v1";
            /** Synthesis Call Count */
            synthesis_call_count: number;
            synthesis_payload_audit: components["schemas"]["SynthesisPayloadAudit"] | null;
            /** Synthesis Prompt Version */
            synthesis_prompt_version: string;
            trace: components["schemas"]["AgentExecutionTrace"];
        };
        /** ReportSection */
        ReportSection: {
            /**
             * Claims
             * @default []
             */
            claims: components["schemas"]["GroundedClaim"][];
            section_id: components["schemas"]["ReportSectionID"];
        };
        /**
         * ReportSectionID
         * @enum {string}
         */
        ReportSectionID: "SCOPE" | "COMPANY" | "FUNDAMENTALS" | "MARKET" | "QUALITY" | "LIMITATIONS" | "EVIDENCE" | "CALCULATIONS" | "AUDIT";
        /**
         * ReportStatus
         * @enum {string}
         */
        ReportStatus: "COMPLETED" | "COMPLETED_WITH_WARNINGS" | "BLOCKED";
        /** ResearchEnvelope[CompanySnapshotResult] */
        ResearchEnvelope_CompanySnapshotResult_: {
            data: components["schemas"]["CompanySnapshotResult"];
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Limitations */
            limitations: string[];
            quality: components["schemas"]["QualityReport"];
            /**
             * Request Id
             * Format: uuid4
             */
            request_id: string;
            /**
             * Schema Version
             * @default 1.0
             * @constant
             */
            schema_version: "1.0";
        };
        /** ResearchEnvelope[FundamentalTrendResult] */
        ResearchEnvelope_FundamentalTrendResult_: {
            data: components["schemas"]["FundamentalTrendResult"];
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Limitations */
            limitations: string[];
            quality: components["schemas"]["QualityReport"];
            /**
             * Request Id
             * Format: uuid4
             */
            request_id: string;
            /**
             * Schema Version
             * @default 1.0
             * @constant
             */
            schema_version: "1.0";
        };
        /** ResearchEnvelope[MarketBehaviorResult] */
        ResearchEnvelope_MarketBehaviorResult_: {
            data: components["schemas"]["MarketBehaviorResult"];
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Limitations */
            limitations: string[];
            quality: components["schemas"]["QualityReport"];
            /**
             * Request Id
             * Format: uuid4
             */
            request_id: string;
            /**
             * Schema Version
             * @default 1.0
             * @constant
             */
            schema_version: "1.0";
        };
        /** ResearchEnvelope[PeriodComparisonResult] */
        ResearchEnvelope_PeriodComparisonResult_: {
            data: components["schemas"]["PeriodComparisonResult"];
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Limitations */
            limitations: string[];
            quality: components["schemas"]["QualityReport"];
            /**
             * Request Id
             * Format: uuid4
             */
            request_id: string;
            /**
             * Schema Version
             * @default 1.0
             * @constant
             */
            schema_version: "1.0";
        };
        /** ResearchEnvelope[ResearchQualityResult] */
        ResearchEnvelope_ResearchQualityResult_: {
            data: components["schemas"]["ResearchQualityResult"];
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Limitations */
            limitations: string[];
            quality: components["schemas"]["QualityReport"];
            /**
             * Request Id
             * Format: uuid4
             */
            request_id: string;
            /**
             * Schema Version
             * @default 1.0
             * @constant
             */
            schema_version: "1.0";
        };
        /** ResearchQualityResult */
        ResearchQualityResult: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /** Available Registered Metrics */
            available_registered_metrics: string[];
            /**
             * Calculation Provenance
             * @default []
             */
            calculation_provenance: components["schemas"]["CalculationProvenance"][];
            /**
             * Evidence
             * @default []
             */
            evidence: components["schemas"]["EvidenceReference"][];
            /** Fundamental Age Calendar Days */
            fundamental_age_calendar_days?: number | null;
            /** Issues */
            issues: components["schemas"]["QualityIssue"][];
            /** Latest Fundamental Available Date */
            latest_fundamental_available_date?: string | null;
            /** Latest Market Session */
            latest_market_session?: string | null;
            /**
             * Limitations
             * @default []
             */
            limitations: string[];
            /** Market Age Calendar Days */
            market_age_calendar_days?: number | null;
            /** Missing Registered Metrics */
            missing_registered_metrics: string[];
            overall_status: components["schemas"]["QualityStatus"];
            /** Provenance Summary */
            provenance_summary: components["schemas"]["ProvenanceRecord"][];
            quality: components["schemas"]["QualityReport"];
            /** Ticker */
            ticker: string;
        };
        /** ResearchReport */
        ResearchReport: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /** Blocking Reasons */
            blocking_reasons: string[];
            /** Calculation Appendix */
            calculation_appendix: components["schemas"]["CalculationAppendixEntry"][];
            /** Evidence Appendix */
            evidence_appendix: components["schemas"]["EvidenceAppendixEntry"][];
            integrity: components["schemas"]["ReportIntegrity"];
            language: components["schemas"]["ReportLanguage"];
            /** Limitations */
            limitations: string[];
            quality: components["schemas"]["QualityReport"];
            quality_status: components["schemas"]["QualityStatus"];
            report_id: components["schemas"]["ReportID"];
            /**
             * Report Version
             * @default research-report-v1
             * @constant
             */
            report_version: "research-report-v1";
            /**
             * Run Id
             * Format: uuid
             */
            run_id: string;
            runtime_metadata: components["schemas"]["ReportRuntimeMetadata"];
            /** Sections */
            sections: components["schemas"]["ReportSection"][];
            /**
             * Selected Skill Id
             * @default equity_research
             * @constant
             */
            selected_skill_id: "equity_research";
            status: components["schemas"]["ReportStatus"];
            synthesis_readiness: components["schemas"]["SynthesisReadiness"];
            /** Ticker */
            ticker: string;
        };
        /** ResearchRequest */
        ResearchRequest: {
            /**
             * As Of Date
             * Format: date
             */
            as_of_date: string;
            /** Ticker */
            ticker: string;
        };
        /**
         * ResponseLanguage
         * @enum {string}
         */
        ResponseLanguage: "AUTO" | "ENGLISH" | "CHINESE";
        /**
         * ResultStatus
         * @enum {string}
         */
        ResultStatus: "AVAILABLE" | "UNAVAILABLE";
        SHA256: string;
        /**
         * Severity
         * @enum {string}
         */
        Severity: "INFO" | "WARNING" | "ERROR";
        /**
         * SourceType
         * @enum {string}
         */
        SourceType: "SOURCE_FACT" | "COMPUTED_RESULT";
        /**
         * SynthesisPayloadAudit
         * @description Only byte counts and object counts; never serialized inputs or provider data.
         */
        SynthesisPayloadAudit: {
            /** Baseline Quality Bytes */
            baseline_quality_bytes: number;
            /** Baseline Request Bytes */
            baseline_request_bytes: number;
            /** Calculation Count */
            calculation_count: number;
            components: components["schemas"]["SynthesisPayloadComponents"];
            /** Evidence Count */
            evidence_count: number;
            /** Instruction Bytes */
            instruction_bytes: number;
            /** Output Schema Bytes */
            output_schema_bytes: number;
            /** Quality Group Count */
            quality_group_count: number;
            /** Quality Issue Count */
            quality_issue_count: number;
            /** Request Bytes */
            request_bytes: number;
        };
        /** SynthesisPayloadComponents */
        SynthesisPayloadComponents: {
            /** Calculation Provenance Bytes */
            calculation_provenance_bytes: number;
            /** Evidence Definitions Bytes */
            evidence_definitions_bytes: number;
            /** Findings Bytes */
            findings_bytes: number;
            /** Limitations Bytes */
            limitations_bytes: number;
            /** Quality Bytes */
            quality_bytes: number;
            /** Request Metadata Bytes */
            request_metadata_bytes: number;
        };
        /**
         * SynthesisReadiness
         * @enum {string}
         */
        SynthesisReadiness: "READY" | "READY_WITH_WARNINGS" | "NOT_READY";
        /**
         * TrendDirection
         * @enum {string}
         */
        TrendDirection: "INCREASED" | "DECREASED" | "UNCHANGED" | "UNAVAILABLE";
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    research_v1_agent_research_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentResearchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResearchEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    equity_research_v1_reports_equity_research_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EquityResearchReportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EquityResearchReportResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Bad Gateway */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    company_snapshot_v1_research_company_snapshot_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResearchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResearchEnvelope_CompanySnapshotResult_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Bad Gateway */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    period_comparison_v1_research_compare_periods_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ComparePeriodsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResearchEnvelope_PeriodComparisonResult_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Bad Gateway */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    fundamental_trends_v1_research_fundamental_trends_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FundamentalTrendsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResearchEnvelope_FundamentalTrendResult_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Bad Gateway */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    market_behavior_v1_research_market_behavior_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MarketBehaviorRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResearchEnvelope_MarketBehaviorResult_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Bad Gateway */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    research_quality_v1_research_quality_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResearchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResearchEnvelope_ResearchQualityResult_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Bad Gateway */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
}
