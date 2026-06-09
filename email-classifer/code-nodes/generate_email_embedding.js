const DEFAULT_OLLAMA_BASE_URL = 'http://192.168.1.100:11434';
const DEFAULT_EMBEDDING_MODEL = 'embeddinggemma';

function trimTrailingSlash(value) {
  return String(value || '').replace(/\/+$/, '');
}

function numberOrNull(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function embeddingVectorFromResponse(responseJson) {
  if (Array.isArray(responseJson?.embeddings?.[0])) return responseJson.embeddings[0];
  if (Array.isArray(responseJson?.embedding)) return responseJson.embedding;
  return [];
}

async function embedItem(json) {
  const {
    embedding,
    embeddings,
    embeddingVector,
    ...safeJson
  } = json;
  const cleanEmailText = String(safeJson.cleanEmailText || '').trim();
  const model = String(safeJson.embeddingModel || DEFAULT_EMBEDDING_MODEL);

  if (!cleanEmailText) {
    return {
      ...safeJson,
      emailEmbedding: {
        status: 'skipped_empty_input',
        model,
        dimensions: 0,
      },
    };
  }

  const baseUrl = trimTrailingSlash(
    safeJson.embeddingBaseUrl || safeJson.ollamaBaseUrl || DEFAULT_OLLAMA_BASE_URL,
  );
  const response = await fetch(`${baseUrl}/api/embed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      input: cleanEmailText,
      truncate: true,
    }),
  });

  if (!response.ok) {
    throw new Error(`Ollama embedding request failed with HTTP ${response.status}`);
  }

  let responseJson;
  try {
    responseJson = await response.json();
  } catch {
    throw new Error(`Ollama embedding response was not valid JSON (HTTP ${response.status})`);
  }
  const vector = embeddingVectorFromResponse(responseJson);
  if (!Array.isArray(vector) || vector.length === 0) {
    throw new Error('Ollama embedding response did not include an embedding vector');
  }

  return {
    ...safeJson,
    emailEmbedding: {
      status: 'ok',
      model: String(responseJson.model || model),
      dimensions: vector.length,
      promptEvalCount: numberOrNull(responseJson.prompt_eval_count),
      totalDuration: numberOrNull(responseJson.total_duration),
    },
  };
}

const results = [];
for (const item of $input.all()) {
  results.push({ json: await embedItem(item.json ?? {}) });
}

return results;
