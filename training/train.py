"""Manifest-checked Nemotron LoRA SFT. Default is an offline plan, never a GPU run."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from simulator.common import canonical, digest

DEFAULT_MODEL = 'nvidia/Llama-3.1-Nemotron-Nano-8B-v1'


def check_dataset(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    identity = {k: v for k, v in manifest.items() if k != 'dataset_id'}
    if manifest['schema_version'] != 1 or digest(identity) != manifest['dataset_id']:
        raise ValueError('Dataset manifest identity mismatch')
    expected = {'train.jsonl', 'validation.jsonl', 'multimodal.jsonl', 'provenance.jsonl'}
    if set(manifest['files']) != expected:
        raise ValueError('Invalid dataset file manifest')
    data = {}
    for name, record in manifest['files'].items():
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('Dataset file hash mismatch: ' + name)
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if len(rows) != record['rows']:
            raise ValueError('Dataset row count mismatch')
        data[name] = rows
    for name in ('train.jsonl', 'validation.jsonl'):
        for row in data[name]:
            if any(not isinstance(message.get('content'), str) for message in row['prompt']):
                raise ValueError('Text student cannot consume image observations')
    return manifest, data


def render_example(tokenizer, row, max_length):
    """Use the student's own tool template; fail if it drops tool calls or truncates."""
    prompt = tokenizer.apply_chat_template(row['prompt'], tools=row['tools'], tokenize=False,
                                           add_generation_prompt=True)
    full = tokenizer.apply_chat_template(row['prompt'] + row['completion'], tools=row['tools'],
                                         tokenize=False, add_generation_prompt=False)
    if not full.startswith(prompt):
        raise ValueError('Student chat template has no stable prompt/completion boundary')
    completion = full[len(prompt):]
    call = row['completion'][0]['tool_calls'][0]['function']
    if call['name'] not in completion or call['arguments']['action'] not in completion:
        raise ValueError('Student chat template does not render tool calls; choose a tool-capable template')
    full_ids = tokenizer(full, add_special_tokens=False)['input_ids']
    prompt_ids = tokenizer(prompt, add_special_tokens=False)['input_ids']
    if full_ids[:len(prompt_ids)] != prompt_ids or len(full_ids) <= len(prompt_ids):
        raise ValueError('Student tokenizer has no stable supervised completion boundary')
    if len(full_ids) > max_length:
        raise ValueError('Example exceeds --max-length; increase it or curate the dataset, never truncate silently')
    return dict(input_ids=full_ids, completion_mask=[0] * len(prompt_ids) + [1] * (len(full_ids) - len(prompt_ids)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--revision', required=True, help='Immutable Hugging Face commit SHA')
    parser.add_argument('--output', default='.runtime/distillation/adapter')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--tokenizer-check', action='store_true', help='Download tokenizer only and validate templates on CPU')
    parser.add_argument('--max-length', type=int, default=8192)
    parser.add_argument('--epochs', type=float, default=2)
    parser.add_argument('--resume', help='Explicit trainer checkpoint directory')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('--revision must be an immutable 40-character commit SHA')
    if args.max_length < 32 or args.epochs <= 0:
        parser.error('Positive epochs and max-length >= 32 required')
    manifest, data = check_dataset(args.dataset)
    plan = dict(model=args.model, revision=args.revision, dataset_id=manifest['dataset_id'],
                training_rows=len(data['train.jsonl']), validation_rows=len(data['validation.jsonl']),
                multimodal_rows_excluded=len(data['multimodal.jsonl']), method='LoRA SFT',
                max_length=args.max_length, epochs=args.epochs, output=args.output,
                execute=args.execute, physical_evaluation='required before deployment')
    print(json.dumps(plan, indent=2))
    if not args.execute and not args.tokenizer_check:
        return
    if not data['train.jsonl'] or not data['validation.jsonl']:
        raise ValueError('Need nonempty train and validation groups; collect more independent seeds')
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision, trust_remote_code=False)
    if not tokenizer.pad_token:
        tokenizer.pad_token = tokenizer.eos_token
    rendered = {name: [render_example(tokenizer, row, args.max_length) for row in data[name]]
                for name in ('train.jsonl', 'validation.jsonl')}
    if not args.execute:
        print('All text examples render without losing tool calls or exceeding the context limit.')
        return
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM
    from trl import SFTConfig, SFTTrainer
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError('A CUDA GPU with BF16 support is required')
    output = Path(args.output)
    run_manifest = dict(plan, tokenizer_chat_template_hash=digest(tokenizer.chat_template))
    if args.resume:
        if not (output / 'run.json').is_file() or json.loads((output / 'run.json').read_text()) != run_manifest:
            raise ValueError('Resume must match the original model, revision, dataset and run configuration')
        if Path(args.resume).resolve().parent != output.resolve():
            raise ValueError('Resume checkpoint must belong to this output directory')
    else:
        output.mkdir(parents=True, exist_ok=False)
        (output / 'run.json').write_text(canonical(run_manifest) + '\n')
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=args.revision,
        torch_dtype=torch.bfloat16, trust_remote_code=False)
    model.config.use_cache = False
    trainer = SFTTrainer(model=model, processing_class=tokenizer,
        train_dataset=Dataset.from_list(rendered['train.jsonl']),
        eval_dataset=Dataset.from_list(rendered['validation.jsonl']),
        peft_config=LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                              target_modules=['q_proj', 'v_proj'], task_type='CAUSAL_LM'),
        args=SFTConfig(output_dir=str(output), num_train_epochs=args.epochs,
            per_device_train_batch_size=1, per_device_eval_batch_size=1,
            gradient_accumulation_steps=8, learning_rate=1e-4, bf16=True,
            gradient_checkpointing=True, max_length=None, packing=False,
            completion_only_loss=True, eval_strategy='epoch', save_strategy='epoch',
            logging_steps=10, report_to='none', seed=7,
            dataset_kwargs={'skip_prepare_dataset': True}))
    trainer.train(resume_from_checkpoint=args.resume)
    trainer.save_model(str(output / 'final'))
    tokenizer.save_pretrained(str(output / 'final'))
    (output / 'evaluation.json').write_text(canonical(trainer.evaluate()) + '\n')


if __name__ == '__main__':
    main()
