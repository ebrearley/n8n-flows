const DEFAULT_EMBEDDING_MODEL = 'embeddinggemma';

function cleanJson(json) {
  const {
    embedding,
    embeddings,
    embeddingVector,
    ...safeJson
  } = json;
  return safeJson;
}

function embeddingMetadata(json) {
  const cleanEmailText = String(json.cleanEmailText || '').trim();
  const model = String(json.embeddingModel || DEFAULT_EMBEDDING_MODEL);

  if (!cleanEmailText) {
    return {
      status: 'skipped_empty_input',
      model,
      dimensions: 0,
    };
  }

  return {
    status: 'disabled_in_code_node_runtime',
    model,
    dimensions: 0,
    reason: 'n8n Code nodes cannot perform the Ollama HTTP embedding request in this runtime; use an HTTP Request node for embeddings.',
  };
}

return $input.all().map((item) => {
  const safeJson = cleanJson(item.json ?? {});
  return {
    json: {
      ...safeJson,
      emailEmbedding: embeddingMetadata(safeJson),
    },
  };
});
