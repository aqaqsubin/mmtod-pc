import os
import re
import cv2
import time
import json
import random
import torch
import openai
import pandas as pd
import numpy as np

from tqdm import tqdm
from glob import iglob
from functools import reduce
from typing import Optional, Tuple, Dict, List
from os.path import join as pjoin

from builder.base_builder import BaseDatasetBuilder
from prompt import TEMPLATES, SYSTEM_MESSAGE
from data_utils import write_json, read_json, mkdir_p, get_extension

class MultimodalTodDatasetBuilder(BaseDatasetBuilder):
    def __init__(self, args, leftovers):
        super().__init__(args=args, leftovers=leftovers)    

        self.belief_states = set([
            "active or not",
            "panic triggering situation",
            "panic disorder symptoms",
            "medications",
            "panic frequency",
            "duration of symptoms"
            ])
        fewshot_samples = read_json(pjoin(self.prompt_dir, "sample_conversation.json"))
        self.fewshot_samples = self.preprocess_dialogue_fewshot(fewshot_samples)
        self.system_message = SYSTEM_MESSAGE

    def preprocess_dialogue_fewshot(self, fewshot_samples: List[Dict]) -> List[Dict]:
        result = []
        for sample in fewshot_samples:            
            response = []
            
            for turn in sample['dialogue']:
                assert set(list(turn['belief_state'].keys())).union(self.belief_states) == self.belief_states, f"Unknown belief state: {turn['belief_state']}"
                response += [f"System: {turn['system']}"]    
                response += [f"User: {turn['user']} => Belief State: {str(turn['belief_state'])}"]

            result += [{
                "context": sample['image_caption'],
                "response": response
            }]
        return result

    def _get_gpt_prompt_example(self, annotation):
        filename = annotation['filename']        
        age = annotation['age']
        emotion = self.emotion_kor_to_eng[annotation['faceExp_uploader']] 
        sex = "female" if annotation['gender'] == "여" else "male"
        
        # make prompt for ChatGPT
        gpt_prompt = self._get_gpt_prompt(age=age, sex=sex, emotion=emotion)
        
        return {
            'filename': filename,
            'gpt_prompt': gpt_prompt,
            'info': {
                'age' : age,
                'emotion': emotion,
                'sex' : sex,
                'annotation': annotation,
            },
        }
    
    def _get_gpt_prompt(self, age, sex, emotion) -> str:
        template = random.choice(TEMPLATES)
        
        prompt = template.replace("<AgeHere>", f"{age}")
        prompt = prompt.replace("<SexHere>", sex)
        prompt = prompt.replace("<SexPronounHere>", "He" if sex=="male" else "She")
        prompt = prompt.replace("<EmotionHere>", emotion)

        return prompt

    def build_gpt_prompt(self):
        for subset in ['train', 'val']:
            if os.path.exists(pjoin(self.annot_dir, f"{subset}.json")):
                print("Already Done: " + pjoin(self.annot_dir, f"{subset}.json"))
                continue

            subset_annot = []
            subset_annot_files = list(iglob(pjoin(self.annot_dir, f"*_{subset}.json")))
            for annot_p in tqdm(subset_annot_files, total=len(subset_annot_files), desc=f"Build {subset} dataset"):
                emotion = annot_p.split(os.sep)[-1].split("_")[0]

                if emotion in self.drop_emotions + ["dst"]: continue

                emotion_subset_annot = read_json(annot_p)
                print(annot_p)
                for emotion_annot in tqdm(emotion_subset_annot, total=len(emotion_subset_annot), desc=f"Build prompts from the annotations in {emotion} folder"):
                    
                    subset_annot += [self._get_gpt_prompt_example(emotion_annot)]

            write_json(pjoin(self.annot_dir, f"{subset}.json"), subset_annot)
                

    
    def _load_previous_result(self, sample_p_regex):
        samples = list(iglob(sample_p_regex))
        samples = sorted(samples, key=lambda x: int(x.split('.')[0].split('_')[-1]), reverse=True)
        if samples:
            print(f"Load {samples[0]}")
            sample_df = pd.read_parquet(
                samples[0],
                engine="pyarrow",
            )
            return sample_df
        return None
    

    def _build_subset(self, annots: List, subset: str, prev_result: pd.DataFrame):
        if prev_result is not None and len(prev_result) > 0:
            history = {row['filename'] + ' ' + row['gpt_prompt']: row.to_dict() \
                    for i, row in prev_result.iterrows()}
            subset_data_rows = [row.to_dict() for _, row in prev_result.iterrows()]
        else:
            history = {}
            subset_data_rows = []
        try:
            for annot in tqdm(annots, total=len(annots), desc=f"Build multimodal DST dataset: {subset}"):
                gpt_prompt = annot['gpt_prompt']
                info = annot['info']
                filename = annot['filename']
                key = filename + " " + gpt_prompt

                if key in history: continue

                row = {
                    "filename": filename,
                    "age" : info['age'],
                    "sex" : info['sex'],
                    "emotion" : info['emotion'],
                    "gpt_prompt" : gpt_prompt,
                    "tagged_dialogue" : self._get_gpt_response(gpt_prompt, num_fewshot= 12)
                }
                subset_data_rows.append(row)
                history[key] = row

                if len(subset_data_rows) % 100 == 0:
                    subset_sample_data = pd.DataFrame(subset_data_rows, columns=['filename', 'age', 'sex', 'emotion', 'gpt_prompt', 'tagged_dialogue'])
                    subset_sample_data.to_parquet(pjoin(self.annot_dir, f"sample_{subset}" ,f"{subset}_sample_{len(subset_data_rows)}.parquet"),
                                        index=False,
                                        engine="pyarrow",
                                        compression="gzip")
        except KeyboardInterrupt as e:
            self.logger.info(f"Save {pjoin(self.annot_dir, f'sample_{subset}' ,f'{subset}_sample_{len(subset_data_rows)}.parquet')}")
            subset_sample_data = pd.DataFrame(subset_data_rows, columns=['filename', 'age', 'sex', 'emotion', 'gpt_prompt', 'tagged_dialogue'])
            subset_sample_data.to_parquet(pjoin(self.annot_dir, f"sample_{subset}" ,f"{subset}_sample_{len(subset_data_rows)}.parquet"),
                                index=False,
                                engine="pyarrow",
                                compression="gzip")


        subset_data = pd.DataFrame(subset_data_rows, columns=['filename', 'age', 'sex', 'emotion', 'gpt_prompt', 'tagged_dialogue'])
        subset_data.to_parquet(pjoin(self.annot_dir, f"{subset}.parquet"),
                            index=False,
                            engine="pyarrow",
                            compression="gzip")


    def build(self):
        # To avoid Too many requests error,
        # we separate building prompt for ChatGPT and generating dialogue stage
        assert os.path.exists(pjoin(self.annot_dir, f"train.json")) and \
              os.path.exists(pjoin(self.annot_dir, f"val.json")), f"Not found annotation JSON file ({self.annot_dir})"

        tr_prev_result = self._load_previous_result(sample_p_regex=pjoin(self.annot_dir, \
                                                                         f"sample_train" ,f"train_sample_**.parquet"))
        
        va_prev_result = self._load_previous_result(sample_p_regex=pjoin(self.annot_dir, \
                                                                         f"sample_val" ,f"val_sample_**.parquet"))
        
        for subset in ['val', 'train']:
            if os.path.exists(pjoin(self.annot_dir, f"{subset}.parquet")):
                print("Already Done: " + pjoin(self.annot_dir, f"{subset}.parquet"))
                continue
            
            mkdir_p(pjoin(self.annot_dir, f"sample_{subset}"))
            annots = read_json(pjoin(self.annot_dir, f"{subset}.json"))
            self._build_subset(annots=annots, subset=subset, prev_result=tr_prev_result if subset=='train' else va_prev_result)
