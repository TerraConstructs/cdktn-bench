#!/usr/bin/env node
"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
require("source-map-support/register");
const cdk = __importStar(require("aws-cdk-lib"));
const scenario_stack_1 = require("../lib/scenario-stack");
/**
 * Generated entrypoint -- generator/gen.py, from specs/iam-e2e-role.yaml.
 * Regenerate, do not hand-edit.
 *
 * No `env: { account, region }` on purpose -- synth-only oracle
 * tiers never need AWS credentials or environment lookups
 * (`cdk synth --no-lookups`).
 */
const app = new cdk.App();
new scenario_stack_1.ScenarioStack(app, "ScenarioStack", {
    description: "IAM E2E role derivation: author deployer + workload permissions against real AWS denials",
});
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXBwLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXBwLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLHVDQUFxQztBQUNyQyxNQUFZLEdBQUcsd0NBQW9CO0FBQ25DLDBEQUFzRDtBQUV0RDs7Ozs7OztHQU9HO0FBQ0gsTUFBTSxHQUFHLEdBQUcsSUFBSSxHQUFHLENBQUMsR0FBRyxFQUFFLENBQUM7QUFFMUIsSUFBSSw4QkFBYSxDQUFDLEdBQUcsRUFBRSxlQUFlLEVBQUU7SUFDdEMsV0FBVyxFQUFFLDBGQUEwRjtDQUN4RyxDQUFDLENBQUMiLCJzb3VyY2VzQ29udGVudCI6WyIjIS91c3IvYmluL2VudiBub2RlXG5pbXBvcnQgXCJzb3VyY2UtbWFwLXN1cHBvcnQvcmVnaXN0ZXJcIjtcbmltcG9ydCAqIGFzIGNkayBmcm9tIFwiYXdzLWNkay1saWJcIjtcbmltcG9ydCB7IFNjZW5hcmlvU3RhY2sgfSBmcm9tIFwiLi4vbGliL3NjZW5hcmlvLXN0YWNrXCI7XG5cbi8qKlxuICogR2VuZXJhdGVkIGVudHJ5cG9pbnQgLS0gZ2VuZXJhdG9yL2dlbi5weSwgZnJvbSBzcGVjcy9pYW0tZTJlLXJvbGUueWFtbC5cbiAqIFJlZ2VuZXJhdGUsIGRvIG5vdCBoYW5kLWVkaXQuXG4gKlxuICogTm8gYGVudjogeyBhY2NvdW50LCByZWdpb24gfWAgb24gcHVycG9zZSAtLSBzeW50aC1vbmx5IG9yYWNsZVxuICogdGllcnMgbmV2ZXIgbmVlZCBBV1MgY3JlZGVudGlhbHMgb3IgZW52aXJvbm1lbnQgbG9va3Vwc1xuICogKGBjZGsgc3ludGggLS1uby1sb29rdXBzYCkuXG4gKi9cbmNvbnN0IGFwcCA9IG5ldyBjZGsuQXBwKCk7XG5cbm5ldyBTY2VuYXJpb1N0YWNrKGFwcCwgXCJTY2VuYXJpb1N0YWNrXCIsIHtcbiAgZGVzY3JpcHRpb246IFwiSUFNIEUyRSByb2xlIGRlcml2YXRpb246IGF1dGhvciBkZXBsb3llciArIHdvcmtsb2FkIHBlcm1pc3Npb25zIGFnYWluc3QgcmVhbCBBV1MgZGVuaWFsc1wiLFxufSk7XG4iXX0=