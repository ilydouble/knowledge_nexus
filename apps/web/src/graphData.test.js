import assert from "node:assert/strict";
import test from "node:test";

import { deriveGraphFacets, deriveSourceDocumentsFromEdges, filterGraphData, getNodeType } from "./graphData.js";

const sample = {
  nodes: [
    { id: "doc-a", uri: "local:///nexus/a.md", label: "Nexus 架构说明", summary: "API and Postgres design" },
    { id: "api", uri: "entity://api", label: "API 服务", properties: { type: "component" } },
    { id: "pg", uri: "entity://postgres", label: "Postgres", properties: { type: "database" } },
    { id: "location_huron", uri: "entity://location_huron", label: "location_huron", properties: {} },
  ],
  edges: [
    { id: "e1", source: "doc-a", target: "api", relation: "MENTIONS", source_file_uri: "local://nexus-a.md" },
    { id: "e2", source: "api", target: "pg", relation: "STORES_IN", source_file_uri: "local://nexus-a.md" },
    { id: "e3", source: "location_huron", target: "pg", relation: "LOCATED_AT", source_file_uri: "local://places.md" },
  ],
};

test("deriveGraphFacets exposes document/entity types and relation names", () => {
  const facets = deriveGraphFacets(sample.nodes, sample.edges);

  assert.deepEqual(facets.nodeTypes, ["component", "database", "document", "location"]);
  assert.deepEqual(facets.relationTypes, ["LOCATED_AT", "MENTIONS", "STORES_IN"]);
});

test("getNodeType infers type from entity id prefixes when properties are missing", () => {
  assert.equal(getNodeType({ id: "object_airhandler", uri: "entity://object_airhandler", properties: {} }), "object");
  assert.equal(getNodeType({ id: "product_shifdr", uri: "entity://product_shifdr", properties: {} }), "product");
});

test("filterGraphData searches node text and keeps only matched nodes", () => {
  const result = filterGraphData(sample.nodes, sample.edges, { query: "postgres" });

  assert.deepEqual(result.nodes.map((node) => node.id), ["doc-a", "pg"]);
  assert.deepEqual(result.edges, []);
  assert.equal(result.hiddenNodes, 2);
  assert.equal(result.hiddenEdges, 3);
});

test("filterGraphData combines node type and relation filters", () => {
  const result = filterGraphData(sample.nodes, sample.edges, {
    nodeTypes: ["component", "database"],
    relationTypes: ["STORES_IN"],
  });

  assert.deepEqual(result.nodes.map((node) => node.id), ["api", "pg"]);
  assert.deepEqual(result.edges.map((edge) => edge.id), ["e2"]);
});

test("filterGraphData can restrict the graph to a selected node neighbourhood", () => {
  const result = filterGraphData(sample.nodes, sample.edges, {
    focusNodeId: "api",
    neighborhoodOnly: true,
  });

  assert.deepEqual(result.nodes.map((node) => node.id), ["doc-a", "api", "pg"]);
  assert.deepEqual(result.edges.map((edge) => edge.id), ["e1", "e2"]);
});

test("filterGraphData searches edge provenance and keeps matching edge endpoints", () => {
  const result = filterGraphData(sample.nodes, sample.edges, { query: "places.md" });

  assert.deepEqual(result.nodes.map((node) => node.id), ["pg", "location_huron"]);
  assert.deepEqual(result.edges.map((edge) => edge.id), ["e3"]);
});

test("deriveSourceDocumentsFromEdges creates graph-only source rows from edge provenance", () => {
  const docs = deriveSourceDocumentsFromEdges(sample.edges);

  assert.deepEqual(docs.map((doc) => doc.uri), ["local://nexus-a.md", "local://places.md"]);
  assert.equal(docs[0].graph_only, true);
  assert.equal(docs[0].chunk_count, 2);
});
