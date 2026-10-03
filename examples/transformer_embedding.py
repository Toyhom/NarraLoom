"""Local Transformers embeddings as a native engine or an OpenAI-compatible service.

Install the optional embedding dependencies and supply a local model directory.
Select the pooling method recommended by the model; BGE-M3 uses cls pooling.
"""

import argparse
import asyncio
import json
import threading
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from roleplay_world.engines import Engine


class TransformerEmbedding:
    def __init__(self, path, model_id, *, device='cpu', pooling='cls', max_tokens=1024):
        import torch
        from transformers import AutoModel, AutoTokenizer
        if pooling not in {'cls', 'mean'} or not 1 <= max_tokens <= 8192:
            raise ValueError('Choose cls/mean pooling and a token limit between 1 and 8192')
        self.torch, self.id, self.pooling, self.max_tokens = torch, model_id, pooling, max_tokens
        self.lock = threading.Lock()
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
        self.model = AutoModel.from_pretrained(path, local_files_only=True, trust_remote_code=False,
                                              torch_dtype=torch.float32).to(device).eval()

    def encode(self, texts):
        vectors, tokens = [], 0
        with self.lock, self.torch.inference_mode():
            for start in range(0, len(texts), 8):
                encoded = self.tokenizer(texts[start:start + 8], padding=True, truncation=False, return_tensors='pt')
                if encoded['input_ids'].shape[1] > self.max_tokens:
                    raise ValueError('Text exceeds the configured token limit; choose smaller memory chunks or a larger model limit')
                tokens += int(encoded['attention_mask'].sum())
                encoded = {key: value.to(self.model.device) for key, value in encoded.items()}
                hidden = self.model(**encoded).last_hidden_state
                if self.pooling == 'cls':
                    pooled = hidden[:, 0]
                else:
                    mask = encoded['attention_mask'].unsqueeze(-1)
                    pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
                pooled = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
                vectors.extend(pooled.cpu().tolist())
        return {'model': self.id, 'vectors': vectors, 'usage': {'prompt_tokens': tokens, 'total_tokens': tokens}}

    async def invoke(self, config, payload, headers):
        return await asyncio.to_thread(self.encode, payload['input'])

    def engine(self):
        return Engine('transformer_embedding', frozenset({'embed'}), self.invoke)


class EmbeddingRequest(BaseModel):
    model: str
    input: Annotated[list[Annotated[str, Field(min_length=1, max_length=16000)]], Field(min_length=1, max_length=128)]
    encoding_format: Literal['float'] = 'float'


def application(embedder):
    app = FastAPI(title='Local embedding example')

    @app.get('/v1/models')
    async def models():
        return {'data': [{'id': embedder.id}]}

    @app.post('/v1/embeddings')
    async def embeddings(request: EmbeddingRequest):
        if request.model != embedder.id:
            raise HTTPException(404, 'Unknown embedding model')
        try:
            result = await embedder.invoke({}, request.model_dump(), {})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {'object': 'list', 'model': result['model'], 'usage': result['usage'],
                'data': [{'object': 'embedding', 'index': i, 'embedding': vector}
                         for i, vector in enumerate(result['vectors'])]}
    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-path', type=Path, required=True)
    parser.add_argument('--model-id', required=True)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--pooling', choices=['cls', 'mean'], default='cls')
    parser.add_argument('--max-tokens', type=int, default=1024)
    parser.add_argument('--port', type=int, default=18112)
    parser.add_argument('--max-runtime-s', type=int, default=3600)
    parser.add_argument('--ready-file', type=Path)
    args = parser.parse_args()
    if not args.model_path.is_dir() or args.max_runtime_s < 1:
        parser.error('Supply a local model directory and a positive runtime limit')
    embedder = TransformerEmbedding(str(args.model_path), args.model_id, device=args.device,
                                    pooling=args.pooling, max_tokens=args.max_tokens)
    server = uvicorn.Server(uvicorn.Config(application(embedder), host='127.0.0.1', port=args.port))
    listener = server.config.bind_socket()
    async def serve():
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError('Embedding service did not start')
                await asyncio.sleep(.05)
            if args.ready_file:
                args.ready_file.parent.mkdir(parents=True, exist_ok=True)
                args.ready_file.write_text(json.dumps({'url': f'http://127.0.0.1:{listener.getsockname()[1]}/v1',
                                                       'model': args.model_id}) + '\n')
            done, _ = await asyncio.wait([task], timeout=args.max_runtime_s)
            if not done:
                server.should_exit = True
                await task
        finally:
            if not task.done():
                server.should_exit = True
                await task
            listener.close()
    asyncio.run(serve())


if __name__ == '__main__':
    main()
