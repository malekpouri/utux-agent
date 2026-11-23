# Public datasets for gold set v0

Task M0-15b. The files below were downloaded on 2026-11-22 from each
dataset's official release location into a directory outside the repository
(`~/utux-data/gold` on the maintainer's machine). **No dataset file is in the
repository.** To check a copy, compare its SHA-256 with the table.

How the datasets are used, and the licence questions, are in
[the gold v0 strategy](gold-v0-strategy.md) (Proposed).

## SciFact

- Official release: the download link of the
  [SciFact repository README](https://github.com/allenai/scifact/blob/master/README.md),
  described in [doc/data.md](https://github.com/allenai/scifact/blob/master/doc/data.md).
- The URL is `release/latest`, so it is not pinned: a later download may
  differ. The hashes below identify the copy used.
- From the archive, only the files with published labels and the corpus were
  extracted. `claims_test.jsonl` has no public labels; it was not extracted
  or opened. The cross-validation folds were not extracted.

| File | URL | Retrieved | SHA-256 |
| --- | --- | --- | --- |
| `scifact/data.tar.gz` | https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz | 2026-11-22 | `11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be` |
| `scifact/data/claims_train.jsonl` | extracted from `data.tar.gz` above | 2026-11-22 | `f4c8fa82d8bd0653a9cc8d61a6ea48c25eacea64e90af5dbf390ebb1b74372f0` |
| `scifact/data/claims_dev.jsonl` | extracted from `data.tar.gz` above | 2026-11-22 | `86f0435d08fdb65d1aa41d1472684f57e6e71930626497bdf4d7a9ec1a632217` |
| `scifact/data/corpus.jsonl` | extracted from `data.tar.gz` above | 2026-11-22 | `b8d6c89624cb2ed74dee8938effc4f5d8bd2086887880af8110d64be4ceade62` |

## SciClaimEval

- Official release: the Hugging Face dataset
  [alabnii/sciclaimeval-shared-task](https://huggingface.co/datasets/alabnii/sciclaimeval-shared-task),
  linked from [sciclaimeval.github.io](https://sciclaimeval.github.io/) and the
  [shared-task repository](https://github.com/SciClaimEval/sciclaimeval-shared-task).
  Version v1.1, the one its card asks users to take.
- Pinned to revision `55ec80b427d9b4eaff8ed9b537a1ea6cb5d665d7` (last modified 2026-08-19).
- Downloaded:
  - the labelled `dev` file of subtask 1;
  - the card;
  - every table in JSON form of `dev` (482 files; 469 are named by `dev` samples).
- Not downloaded:
  - figures and table images, since figure evidence is dropped;
  - the LaTeX and HTML tables;
  - the papers;
  - subtask 2, which pairs the same claims with two pieces of evidence.
- There is no labelled test file: the test labels are not public.

| File | URL | Retrieved | SHA-256 |
| --- | --- | --- | --- |
| `sciclaimeval/README.md` | https://huggingface.co/datasets/alabnii/sciclaimeval-shared-task/resolve/55ec80b427d9b4eaff8ed9b537a1ea6cb5d665d7/README.md | 2026-11-22 | `c6425da32f6fe8bb3129eee06b05491188960cfbccf4895fcd5f604a3495e863` |
| `sciclaimeval/data/dev_task1_release.json` | https://huggingface.co/datasets/alabnii/sciclaimeval-shared-task/resolve/55ec80b427d9b4eaff8ed9b537a1ea6cb5d665d7/data/dev_task1_release.json | 2026-11-22 | `cbf0db967f285875b7b283ed56f4fed93bf4627f84d8e7f3c39489bc56f289ab` |

<details>
<summary>The 482 table files, <code>data/tables_json/dev/</code></summary>

Each is at the revision URL above followed by `data/tables_json/dev/<file>`,
retrieved 2026-11-22.

| File | SHA-256 |
| --- | --- |
| `val_tab_0001.json` | `9f22dc82837358a5baf43b988f32ca463c440e8161b8b6bd5083e82d118f529d` |
| `val_tab_0002.json` | `72d03e4903692f1edc121bb1bb53739e88895ea391f832ef905506dac8de9e9d` |
| `val_tab_0004.json` | `df7bb1488d3d2cc5da59ac3d2a00f31beb459fe842290961e30c7e40771a4f95` |
| `val_tab_0005.json` | `b876010b7c442e29bf946cc9e9a70461ad63fa6297993357e86316c0d1ee99e2` |
| `val_tab_0006.json` | `b876010b7c442e29bf946cc9e9a70461ad63fa6297993357e86316c0d1ee99e2` |
| `val_tab_0008.json` | `595f9e1c20236d299cbd9efbfbca0c8846886fc5925faa1500e287053811b29e` |
| `val_tab_0009.json` | `fc1d55b2a77276138d82f66637530ac7d44c087072d230f344f4e454d5706cfa` |
| `val_tab_0010.json` | `f4f28e950bbf3d1a146da5b63feac0ccd48a3f9dcb4ca660d90472a14a8aa805` |
| `val_tab_0016.json` | `497be4d664dbfa3c87d2d381a1f4633c361547f09f928d330f3c09c5d9ef1ca5` |
| `val_tab_0017.json` | `497be4d664dbfa3c87d2d381a1f4633c361547f09f928d330f3c09c5d9ef1ca5` |
| `val_tab_0018.json` | `feca304d5e852af008ec7b186265870ab5b7d935d13727437c7cccf16ca188f4` |
| `val_tab_0019.json` | `497be4d664dbfa3c87d2d381a1f4633c361547f09f928d330f3c09c5d9ef1ca5` |
| `val_tab_0020.json` | `497be4d664dbfa3c87d2d381a1f4633c361547f09f928d330f3c09c5d9ef1ca5` |
| `val_tab_0022.json` | `fa7ffd916d8039fd3bf45edd81508470e26e55cf4bb6f630aa1f16e95898f920` |
| `val_tab_0023.json` | `3bf427d4a7c2487cea02eb01b71c94b69cfe8e5d66a3cc1c6a8f586bd7a50503` |
| `val_tab_0026.json` | `27e89509c4e5812d7e757bb2d01a7f6e43e841e599d4ffd970de6dd7a0c1cda7` |
| `val_tab_0027.json` | `7bff2c70d7ad06846aff1f3ae0dbdd51dcd3589adc094dbe847bfa5f29626bf1` |
| `val_tab_0029.json` | `4f1e09327f5f3f754a9b02ed5adc7d9c4ac51d393fdf5575a99ff10127618a6f` |
| `val_tab_0030.json` | `236e46402d518aa13d53742353c3b49094ec8b167d351383261c43b2ed4a1527` |
| `val_tab_0031.json` | `c574554e7fe5b9078a35edd83cf8a2351c49b3a710a17cb2d5b44ae338306b88` |
| `val_tab_0032.json` | `329b59f24ae1aec329076222dcd0954c9c3e05483ac72a3066d939e52e6fa2ee` |
| `val_tab_0033.json` | `c574554e7fe5b9078a35edd83cf8a2351c49b3a710a17cb2d5b44ae338306b88` |
| `val_tab_0034.json` | `c574554e7fe5b9078a35edd83cf8a2351c49b3a710a17cb2d5b44ae338306b88` |
| `val_tab_0035.json` | `5d8bf34e26f13a6a329fce6b93b4a51a813301e00de78b76436ca9ac7fe5419b` |
| `val_tab_0036.json` | `2eb8dc212682974de91533ef611b7bf4ad33f710ee4526ad6712896491537cb8` |
| `val_tab_0037.json` | `df98d40074d2fbffb7829f5236981a478a8999ec83d067fd7ac50f50a65c1cac` |
| `val_tab_0038.json` | `932f43002970bdc21121cc4f5867ca537045e1abad353453cf8ab69bee1e520a` |
| `val_tab_0040.json` | `fb8999022895a2d9c5cd0cf123dcbaa94df49fb73a05507bca691d05fa33bbf7` |
| `val_tab_0041.json` | `98b5b7fa54cc7d9b1938344c671dc1e57d981bf31857be368415307c35d75736` |
| `val_tab_0042.json` | `b680c56b12d35bba62ba4120c5a89588be11081281017c5334f34754bddc02c2` |
| `val_tab_0044.json` | `fb5ec096f01eb7028b5fe00ec5511aea2867fe925e2a6d82e4e1287f607ae5f5` |
| `val_tab_0054.json` | `e6b05698f6d66a6e0f7b5261f054fd238a02cd4e1d27a5c707536cd9c81d8a33` |
| `val_tab_0055.json` | `558145380f1f6183e184f205ee1438fff2fd7ef039c55772b6aa7f71dd827d67` |
| `val_tab_0056.json` | `e6b05698f6d66a6e0f7b5261f054fd238a02cd4e1d27a5c707536cd9c81d8a33` |
| `val_tab_0057.json` | `e6b05698f6d66a6e0f7b5261f054fd238a02cd4e1d27a5c707536cd9c81d8a33` |
| `val_tab_0058.json` | `a254d899c5368232d08dcd64de2fad346dbe429c79be03bcc4203e871b4cb840` |
| `val_tab_0059.json` | `4701bab88d31517c882341d7ab7a14f7bed5e0e796eed51c7e36f4302b9a4fce` |
| `val_tab_0060.json` | `c294d80a90127344c8ebf14ab4974ad389d5cf70503e47b01ef1c4cbe4629496` |
| `val_tab_0062.json` | `3082b6baf80ed7bb7a796bef3fe3a2b26bac655b2dd9e22ed48331fbbae5e160` |
| `val_tab_0064.json` | `468f61b24d4373cba431ac95b8e8e7f48089af9c3974e678196fe35088dd1b58` |
| `val_tab_0065.json` | `89f754e78c99e0433c1fe557d5203ccdfa56c5c91f4d07c1329e1a6bd768eb1b` |
| `val_tab_0066.json` | `dcd289ca6916ed3583ba77212bf6ee58172506db80552eedaf21b96f671f8db0` |
| `val_tab_0067.json` | `d87cb4bbf37b883d71c0367a4e018677ab82ac3c55966a85e9dc7553fc521ac8` |
| `val_tab_0068.json` | `d87cb4bbf37b883d71c0367a4e018677ab82ac3c55966a85e9dc7553fc521ac8` |
| `val_tab_0069.json` | `1bef17ada7c50488444a0fd32c3a6a926c8a0f292a643411f956eebb56b7d4ad` |
| `val_tab_0070.json` | `0eeaa0f93590182a3ea3a2c2a5915299873b915737cc43a2647d9760ac8fb7df` |
| `val_tab_0072.json` | `14bc4eec53a2e2b1f21e7f9323ef978997706768591c486e292a9e031213b324` |
| `val_tab_0073.json` | `8bc3a8f8c1af08e1c2c37ef90a8f0f1d025ad777664136145daf04d69de808c8` |
| `val_tab_0074.json` | `8bc3a8f8c1af08e1c2c37ef90a8f0f1d025ad777664136145daf04d69de808c8` |
| `val_tab_0075.json` | `cf28eefd1d4b2ee4110c800c68cfef83199455fb612cb28a0232fffe5a6dcea2` |
| `val_tab_0076.json` | `a68249e17b87cdcbbb0255d6e8b5c414d46e5cafe982b2a5b54876cfcb17979c` |
| `val_tab_0077.json` | `df7bb1488d3d2cc5da59ac3d2a00f31beb459fe842290961e30c7e40771a4f95` |
| `val_tab_0078.json` | `3227949749898c098bd826860a5891948be16c28c7c37418fc35fc46af3a73a3` |
| `val_tab_0079.json` | `0665fb523e2967235a848b5a8829b4d95cd489c9df4522253e0dc9bd7a7a4bae` |
| `val_tab_0080.json` | `f8abd39375413f2828280a26e8deb2c8d8bd94bdc7f5be7461228534a217d1f7` |
| `val_tab_0081.json` | `0665fb523e2967235a848b5a8829b4d95cd489c9df4522253e0dc9bd7a7a4bae` |
| `val_tab_0082.json` | `2004411e54ecc4e0b19960e5938fa02a1deaa3ade5b71648b026cd3dfb5a0b68` |
| `val_tab_0083.json` | `15b8fadd05d2bca39e508376c06e7487ad3affb6d8b2781c512f7c5ad3fb2795` |
| `val_tab_0084.json` | `2004411e54ecc4e0b19960e5938fa02a1deaa3ade5b71648b026cd3dfb5a0b68` |
| `val_tab_0087.json` | `6a2b7376f76c655e27819522b56bead64b526a4f5afaa71d2dc5190efd8f01c7` |
| `val_tab_0088.json` | `d439672fc476e9e2466152bd62d8f28c17c46c06665d95e9d6840f72db491f5c` |
| `val_tab_0089.json` | `052740221701b39493d739c16b4fc4cf6d6cf2e53ebba84ffea2e0228ede81c8` |
| `val_tab_0090.json` | `14e7c33451f763b4230a73927083756310ff8846d30f453b37255fc184af67f8` |
| `val_tab_0091.json` | `052740221701b39493d739c16b4fc4cf6d6cf2e53ebba84ffea2e0228ede81c8` |
| `val_tab_0092.json` | `636ca838a8d7545620f4f44d2bdfcc192c867aa9adbf0c3f31376d22b7047887` |
| `val_tab_0093.json` | `4cfbf361e2ef892c2fef54dc986816a7d7fa06c8aa32cb7304da2ab293618ef1` |
| `val_tab_0094.json` | `11e4389f58a5fae18f3fe18c59142a4d5544ec6049c59f5063567fec81649878` |
| `val_tab_0095.json` | `dbaba0584fe10ac7b64835b4c4f84e6fd405b63052e42f8560e170bd0f25bb7c` |
| `val_tab_0096.json` | `c9027722d7356b77d72d7a784a78f0b7184632791058150302a0052c69b5dc7e` |
| `val_tab_0097.json` | `30592d03d38deea43aac2a7dc272f85e0b9603afebeeed6a8419b2fb57bf285b` |
| `val_tab_0098.json` | `c9027722d7356b77d72d7a784a78f0b7184632791058150302a0052c69b5dc7e` |
| `val_tab_0099.json` | `3a522ffe2b2ca188cd148c65400fcab5ab794348655c9af89307329c626378a4` |
| `val_tab_0100.json` | `c9027722d7356b77d72d7a784a78f0b7184632791058150302a0052c69b5dc7e` |
| `val_tab_0101.json` | `ffd88c795563ac52c8dfd85b71974e78711d6a055f63316d8b76990f5f593dae` |
| `val_tab_0102.json` | `5a3400dc4a74aaf668d8361057d0b2ecd50c99b3b620b1e5d71de813578d5c8f` |
| `val_tab_0103.json` | `c490a1e020e8ccf543df832a8849d2b0baca3c34982f6dab257441fef7bb7c5e` |
| `val_tab_0104.json` | `29f2fc011d78b90ecace159f2a9babce9b95348ceac66d325fa5d515de167494` |
| `val_tab_0105.json` | `f0f0a66971a462267de74afcd40e93b151ee1feeab9f0f0cdef4723ac84fee35` |
| `val_tab_0106.json` | `45f22edb318967496b8a120a6874e47ea5c40ad80b15c60c5b7561de143ea4a6` |
| `val_tab_0107.json` | `c6e74ae22787544eb16aadd904d8eef9523672ac95cbb263640d1fa936d3f93d` |
| `val_tab_0108.json` | `ae0e8037ef2eb94522c863019fbb06f7aa7ac98beee3cd3d0d9b2cd23611c692` |
| `val_tab_0109.json` | `e46105b0b4ac5bf1ae4a71a5d439faf28816d37e9f226110e7dedb810b303255` |
| `val_tab_0110.json` | `e07c131bd834f486c33e4ffeddb7e1884896966a8b6dbf69f3871e3a597211d2` |
| `val_tab_0111.json` | `e46105b0b4ac5bf1ae4a71a5d439faf28816d37e9f226110e7dedb810b303255` |
| `val_tab_0112.json` | `3392496a32d23fc31a07bfacdc333fade512d2b014bf13b0aa17e50f0aad3a66` |
| `val_tab_0113.json` | `f3a4353bc5327dc07e092f726570221bcd186a0585f51bb10b7f4bd8ea77ccce` |
| `val_tab_0114.json` | `3392496a32d23fc31a07bfacdc333fade512d2b014bf13b0aa17e50f0aad3a66` |
| `val_tab_0115.json` | `df5fcf5aa30328fd4ecc6abc84f7239e3e7960b5a94085fbc7d6f5cbeebfc68d` |
| `val_tab_0116.json` | `0bc51fcec936b282b13006b2cc484f2ec010a6c164e6beee451f89c62a2be916` |
| `val_tab_0117.json` | `a567fa6b44911de715d25b2cbfcbe926e18bba42fab6a31e5debfdff70a8c327` |
| `val_tab_0119.json` | `0bc51fcec936b282b13006b2cc484f2ec010a6c164e6beee451f89c62a2be916` |
| `val_tab_0120.json` | `dcd693114870b01646907f183347f906cd50ef83deee53a0f66c24aedf7086b8` |
| `val_tab_0121.json` | `ca17d1b4ecf5425c1dcc8fa0849649620f2fc7cde9747b323e81adc35c2a71b1` |
| `val_tab_0122.json` | `c316264a390961031cc37a916ccaab7c1b18a216b0b0a33eecda67ec385457ae` |
| `val_tab_0124.json` | `f32d45c0ffd2eb042bc808fb51b950426e5e8970fb20145380b07c6613b308b6` |
| `val_tab_0126.json` | `52c803e3b87fbc6f13db943617e74e360f89efd66175c02e42d508cd81818dcf` |
| `val_tab_0127.json` | `d68d0691dc1678a50b1dd05b50d2ac88fe896715ca4ee3bd97e696bf5c5fc13f` |
| `val_tab_0130.json` | `fe872493c8ac36b022f46f02758135552e261218e0e2509582392eb408cc7b46` |
| `val_tab_0131.json` | `15921efb2b6fa23dff70d22d33fc0b44d88d2d49e0e9681a25a7fda3294cedd5` |
| `val_tab_0132.json` | `6d50184de16bd88aab9cdb16df44b5e49bab39319d501e48a38577fcf4b02bdc` |
| `val_tab_0133.json` | `cbee932acb1afccfc6bb0df1ed06a65f4079477354c31e27faf38d6230073182` |
| `val_tab_0136.json` | `b26dceaa0aa589de9d3345f5d8527af09cf61ccf734058034a66ba092a7c8aa9` |
| `val_tab_0138.json` | `bd011cd6dd4805207f093132dbf5f2d23d4b4d669b5a42c77cb8f326bb0187bd` |
| `val_tab_0139.json` | `8d4d21dbcb8e869bfd09fc5e8c60dd87216e0614c58a5bc028683e88d9c42579` |
| `val_tab_0141.json` | `7f5be99227218472df646dd2eeb7ba69758bb48ec86c1f10a2af31d2fa45f8b0` |
| `val_tab_0142.json` | `20b0c3f92e8239d0874be1de3728b53c03332d9cbd5b41abbc121254622b252f` |
| `val_tab_0143.json` | `afffc06d989134e6dddd1d92996dd51e968a2d3c687daa9aaa1215416e69753d` |
| `val_tab_0146.json` | `d9d5765c1765ee1977f4925b18323497203f3dcaf6abb52f748b7460dce083f1` |
| `val_tab_0147.json` | `276ee42b6c77d5eed1633b223c97c97438446da56898a20cc8d7f012593c0574` |
| `val_tab_0149.json` | `8271f8247114d1c496fd9eab3d9c4387cba738f6b057a70542faffe992832c97` |
| `val_tab_0150.json` | `a25b7b4d1bd48d07a1a197d0601f97770272a98ba5c534b8095c4833c02edd15` |
| `val_tab_0151.json` | `8271f8247114d1c496fd9eab3d9c4387cba738f6b057a70542faffe992832c97` |
| `val_tab_0152.json` | `72e1462ba6cd3236a8f1e755a430fa9543e9859db94f69a2925e8bae46a6a8ac` |
| `val_tab_0153.json` | `156181c00481d667347bb251343246688e58c9168afaf48046aea1535b7b1e15` |
| `val_tab_0154.json` | `f00f0c8e9f970902c41e3320603c7cb58ee6c8950518fba3b0e33b43657d5298` |
| `val_tab_0155.json` | `156181c00481d667347bb251343246688e58c9168afaf48046aea1535b7b1e15` |
| `val_tab_0156.json` | `6ac3d5e27c93885dc0be0b234912d308acd7eab51350f3305b46f50be58cde13` |
| `val_tab_0157.json` | `546d1abc270df4f7a84e4bcec4fe9c4330712e529e38950242c2de20dfae4fb2` |
| `val_tab_0158.json` | `726d6006349980f0b13b2b92039f8aaaa3c3e31e86169b8396315346af5607b6` |
| `val_tab_0159.json` | `b580b6c839f3670e376afd4aec1eee79123b888aa39ab4e18a964ba829e6b18e` |
| `val_tab_0160.json` | `2dfc68851ba79d49f8b970838e517e702983be4f28d0511db6bee1360a1d2ab5` |
| `val_tab_0161.json` | `b580b6c839f3670e376afd4aec1eee79123b888aa39ab4e18a964ba829e6b18e` |
| `val_tab_0162.json` | `24b5248e1296564a19094a84a73fff0b7d74d5df3197bb1804fbc675f38ac4bb` |
| `val_tab_0164.json` | `8d82eaecdb98e366a842cd83590c7be30efbeefff3ebbb41823a28c4e27e88d1` |
| `val_tab_0165.json` | `059af60a1896d7e5dc3e5e63cbb497b38deab0ea7695e4e52831d39d22692e00` |
| `val_tab_0166.json` | `d25fcc659e70f3f6c9fcf1725fc942459beb070a1e610fabab63866231591325` |
| `val_tab_0168.json` | `2efc1adb3166c0c7919048aaa1ccac6ee4546f346ed0a847b80004e0f59f6e58` |
| `val_tab_0169.json` | `282d318fdc20b19eddfbaaf12779614b7a9281645b36f324ba6126a0ef6eef0e` |
| `val_tab_0173.json` | `2efc1adb3166c0c7919048aaa1ccac6ee4546f346ed0a847b80004e0f59f6e58` |
| `val_tab_0174.json` | `87ddd04647f2b6495e81a67aa94dfd27df4d686d7406bb0caf527d3634f9ec42` |
| `val_tab_0177.json` | `75a3843fb51d4a7081c8d69a718c24deacfe603f427ef53ea25697cb481fa6e3` |
| `val_tab_0178.json` | `75a3843fb51d4a7081c8d69a718c24deacfe603f427ef53ea25697cb481fa6e3` |
| `val_tab_0179.json` | `0f2e4c87962085c2f0f5b224636ec03324b2fe12d05e9f615942d95466c47582` |
| `val_tab_0181.json` | `5e89a4d4538e10d96b67d20b71569eaa2417940e25ab682557218ccfa2daccc4` |
| `val_tab_0182.json` | `c0ae85debf272f59ff8c952863ac8c56150c0d5db290fe5a3ecedc1718926bdd` |
| `val_tab_0183.json` | `04d4d01c87a4fe49740bccfb1a43332e1c533ae357673b67fc8da7860921a1e1` |
| `val_tab_0184.json` | `c0ae85debf272f59ff8c952863ac8c56150c0d5db290fe5a3ecedc1718926bdd` |
| `val_tab_0185.json` | `86dd81ec6a95dc20a72e1685054b252ee37ac9da09dd6dbfb1b738b887269d80` |
| `val_tab_0188.json` | `9a64ff5478aab81609c9fdc2af52e8a695371b5c166547cb12d6fad60ded93c1` |
| `val_tab_0189.json` | `513e7bc003335a925d1f8273dbc1fa747cdef60b74796571d1058017fe541ef5` |
| `val_tab_0191.json` | `28c93f136259a30d2b610ba6a4cc8e24047620b709e48d324827783f21cf81fd` |
| `val_tab_0193.json` | `bec0b0858cfbfef4c92057fb3b759c8a54b47206d6b04316d8eca5b1910bcda5` |
| `val_tab_0194.json` | `ed78e8312d80aee24a3e9d368524946bfbd83dc3b8ffbbc9f2068ad2df065633` |
| `val_tab_0195.json` | `be098afdee1ad1fef65c590fe7479fb8ba572a050babb8ab30fadd4e4e02fced` |
| `val_tab_0196.json` | `ed78e8312d80aee24a3e9d368524946bfbd83dc3b8ffbbc9f2068ad2df065633` |
| `val_tab_0197.json` | `dbd5548de03aecfd449705c052bb2fd70a8a17e68afd66c43f31c5c1343908c0` |
| `val_tab_0199.json` | `dbaba0584fe10ac7b64835b4c4f84e6fd405b63052e42f8560e170bd0f25bb7c` |
| `val_tab_0200.json` | `c3818b830b3ed36e770a84dadf374926806b090d4423ef7e0636ed34c53ff24c` |
| `val_tab_0201.json` | `ed78e8312d80aee24a3e9d368524946bfbd83dc3b8ffbbc9f2068ad2df065633` |
| `val_tab_0202.json` | `6fdbbdb246df3801d06c7dcc3e842f19dad302b1a6295025a32805963bd8e455` |
| `val_tab_0203.json` | `6fdbbdb246df3801d06c7dcc3e842f19dad302b1a6295025a32805963bd8e455` |
| `val_tab_0204.json` | `0902db1c62260815f07eb7b0d10951b7d7f25cf8a79ee8375aabd6a8188c0b02` |
| `val_tab_0205.json` | `1c23ce2409716be20d637ee7b46a99df3e78ce999a5609d4310d3b19dc9fb273` |
| `val_tab_0206.json` | `972f17f43ca1b9ebdbbfe88c42d4117f1432d35f40b1f131139170a62d7c1d39` |
| `val_tab_0208.json` | `4a844ca6675f05a13f55671834c57442813620746e09fd2e47c389596ae5cb36` |
| `val_tab_0209.json` | `731e29321acc5faaec60f34a835877f848dc80bb3c0516e4146e0c42970fea77` |
| `val_tab_0210.json` | `945e2601a9bee7db2aac64c1f84b257a9b70319452bf1effacd82103bdb24c31` |
| `val_tab_0211.json` | `2d7e634d64ad9ad0cd6cb80f9fde7331df3e58e4b2b3f18933e2f06f00f57992` |
| `val_tab_0212.json` | `945e2601a9bee7db2aac64c1f84b257a9b70319452bf1effacd82103bdb24c31` |
| `val_tab_0213.json` | `aafaa3da2dbcdf48a2f2d9f0ff70d51569474f9278e451f79b26176d0fea6442` |
| `val_tab_0214.json` | `074e0eb7e918e78ae86e70c76f5f6fcf51a75ad379b2792d45d73ba4b5302d78` |
| `val_tab_0215.json` | `6c9c2642de3e559737b061326f337b1da9364c2e562ff7177fd5d4454b086871` |
| `val_tab_0216.json` | `6c9c2642de3e559737b061326f337b1da9364c2e562ff7177fd5d4454b086871` |
| `val_tab_0217.json` | `e424b48804acd7a99e3a1e5bbce33cee912f5af8bd67075308fa9d86e7b40104` |
| `val_tab_0218.json` | `6d612d64578e2ed83f50bc177caf1839b9189a82c626c43f1d27f1969abfd54b` |
| `val_tab_0220.json` | `c4dad2ebb7c5b5026a37512803ef0e20a79ae052e71d1c357bbdbb637d76269b` |
| `val_tab_0221.json` | `b461376dafdad7f12a516584944842bb28912550942b2331649fb7d6292549bf` |
| `val_tab_0224.json` | `c8a4869e01ba8772a2c78cbefad300949bd149b6b7cba29b5657ab4abe779705` |
| `val_tab_0225.json` | `c8a4869e01ba8772a2c78cbefad300949bd149b6b7cba29b5657ab4abe779705` |
| `val_tab_0228.json` | `ce4a6ec2def0bf512adee5500f654aaf8f07ccb11834921ebe609147803f2eea` |
| `val_tab_0229.json` | `a852bdc047da26c612fff4b867928facba48db5238c56688f2605cceb5e58b6b` |
| `val_tab_0230.json` | `8ea9fc83137fd8c76e7423ba4a500692943d76449770449add050094b86a7f42` |
| `val_tab_0231.json` | `8ea9fc83137fd8c76e7423ba4a500692943d76449770449add050094b86a7f42` |
| `val_tab_0232.json` | `c4580b358e1a8ce03eb6ec29ebe5419137742dfd3682555a3e85a262181ef703` |
| `val_tab_0235.json` | `655f4f3b8d9dc5a99d93a6d4d0748e08e31913cfa56f75c7548f3d8a9c1ea0a5` |
| `val_tab_0236.json` | `d793eb808549e118f26d20727cffa35eb785fb9613865bf633c9e6681151713f` |
| `val_tab_0237.json` | `13ad0783fffc98efce5614b9b4ec6316a6c98ad0ecae12809f03c3b98ee07529` |
| `val_tab_0238.json` | `4a0ae8b437be560c2b24a640f78108b38cff9cbf0b9cd6295ca14a8c0b3af3e7` |
| `val_tab_0239.json` | `ce4a4c326330599a441ac180d77c3d330f100543a3fae8f4a209253b1b8e7fe8` |
| `val_tab_0241.json` | `ce4a4c326330599a441ac180d77c3d330f100543a3fae8f4a209253b1b8e7fe8` |
| `val_tab_0243.json` | `f79a0995849f7e346a7862108e7e1ff842370004a690794ff02d2fe596d11eb6` |
| `val_tab_0244.json` | `9e42b84b20254b474e48121902e98dcd33726ed644175b232a3ef054c448981e` |
| `val_tab_0245.json` | `e5bbe2c193b88554d4d22e1f1816c5f5f28bbf1ef20dc2577a978a4de87fa4ef` |
| `val_tab_0246.json` | `e5bbe2c193b88554d4d22e1f1816c5f5f28bbf1ef20dc2577a978a4de87fa4ef` |
| `val_tab_0247.json` | `f207a34b615638735e87dc3afcbc8932b3ae961b897f5ea5ed430bcafe66ac90` |
| `val_tab_0248.json` | `e5bbe2c193b88554d4d22e1f1816c5f5f28bbf1ef20dc2577a978a4de87fa4ef` |
| `val_tab_0249.json` | `c0f934c4f0d7b7a233d0e5f953cb8cecbf2f597496c923430df1bae69c7920bd` |
| `val_tab_0250.json` | `2220caa15c9bc0d5b16a75cf13c9f0afbe9c5e4d88eb9a5bfce6c831576e78a0` |
| `val_tab_0252.json` | `ffd88c795563ac52c8dfd85b71974e78711d6a055f63316d8b76990f5f593dae` |
| `val_tab_0253.json` | `d274b3c462e65562aee8c05cb97b5fc0ba78979f21482720d414d98bbb3c6295` |
| `val_tab_0255.json` | `c490a1e020e8ccf543df832a8849d2b0baca3c34982f6dab257441fef7bb7c5e` |
| `val_tab_0256.json` | `8d59a69218ebbc1e6924a138e8df6cc1b586495a254d9e2da46044bb6a3f20ab` |
| `val_tab_0257.json` | `8d59a69218ebbc1e6924a138e8df6cc1b586495a254d9e2da46044bb6a3f20ab` |
| `val_tab_0258.json` | `998918860e096cce84564c02964064f383b2f5494fc7b9eef953a229a7d50044` |
| `val_tab_0260.json` | `5553932113a731ca6893dd252fb7c7af5caf9f39a8496fb22ca964d19b6778e0` |
| `val_tab_0261.json` | `22c34e1b31b6e8c043f0ff822ea14fba5c099bfe871f01874a9492a775893f47` |
| `val_tab_0262.json` | `5553932113a731ca6893dd252fb7c7af5caf9f39a8496fb22ca964d19b6778e0` |
| `val_tab_0263.json` | `0578bf1b564611121699a763d9b9c38f87848a7da45b8aa5e94e6f92a99eb281` |
| `val_tab_0264.json` | `5553932113a731ca6893dd252fb7c7af5caf9f39a8496fb22ca964d19b6778e0` |
| `val_tab_0265.json` | `0f4fd7b1fd82568f3cb61d7112cdf262763978d0eec4e4812344561a94eded09` |
| `val_tab_0266.json` | `5553932113a731ca6893dd252fb7c7af5caf9f39a8496fb22ca964d19b6778e0` |
| `val_tab_0267.json` | `85e582a9bb1b508e5bb650977ddaf74eb67ba0095f062d879db0320e26d143a1` |
| `val_tab_0270.json` | `6db378d921e4312105bdb88b2089cc779e3cc016f14554f5994e4683f2a8c15e` |
| `val_tab_0272.json` | `01a6cccade3f6d2679ebe6380c2207dd96aa983754a91e2200962aea110c2189` |
| `val_tab_0273.json` | `53c6d1de296e7521c1ab40583656028dc8331aca73cc3f2fc3af39d878fcff18` |
| `val_tab_0274.json` | `c6e74ae22787544eb16aadd904d8eef9523672ac95cbb263640d1fa936d3f93d` |
| `val_tab_0275.json` | `3f607e8b6f9786777ade288534a6a3c934e1b3de6209b9674ff45defbc2d60bb` |
| `val_tab_0276.json` | `e46105b0b4ac5bf1ae4a71a5d439faf28816d37e9f226110e7dedb810b303255` |
| `val_tab_0277.json` | `5a5dad41544ffea93e1b16ed4cee67822b60b6eb290fdf3e0e7fdd8c5e9530eb` |
| `val_tab_0278.json` | `32d81f5621844f5774222bed882c456e826a19721a69c7565b8332df1991f163` |
| `val_tab_0279.json` | `18ddb07677a21a9bc167143fc311bb42d6abc1fca65c1db8e8a4d6c1a0a7091d` |
| `val_tab_0284.json` | `3589ba5935faf124a371ce93536614e038f35d342b1108ef5959fbf8815ffe9f` |
| `val_tab_0286.json` | `b876d953c064db259b8db5dd58904f411b00c5a0d9c063fd84c4e276c768696e` |
| `val_tab_0288.json` | `f32d45c0ffd2eb042bc808fb51b950426e5e8970fb20145380b07c6613b308b6` |
| `val_tab_0289.json` | `3d3b89bf714f1a0d01aafd5717271dfa23c03211f9c56ea04e0857823c6253a1` |
| `val_tab_0290.json` | `cac770e9b911dff056ffa2ac2945a8f64936aab793f4ee7b0a563336571f7c47` |
| `val_tab_0291.json` | `5d380ee5c7cb86c75d845d4cd669b41df9afa444dc2a913cba868d8725ed32fa` |
| `val_tab_0292.json` | `24403c0651997c85f078def99747707f2ad4b4dfc1d58cc0f3f2ba5ff6a6078e` |
| `val_tab_0295.json` | `e6cbf32262a090060e0922be82eda44181573d765ac0b227db0a762ec0a76e1b` |
| `val_tab_0297.json` | `fc441b04c71c68f781532cc18d474a5de1c237112bd39b1dec1af73ca334f7f7` |
| `val_tab_0298.json` | `fae34599b524ec2072de7609880516d5cecf6ee57129cf604317c5d231b556ec` |
| `val_tab_0299.json` | `02908258024e66ac3ec87973f6fc895549d69f94361c4030fa805cd67c7eebac` |
| `val_tab_0300.json` | `89723095af5b7cf73dfb8716529f7cadbc9f9f4a012db5421390ec4953c31021` |
| `val_tab_0301.json` | `f807a4d44526074ed12e1ff2069f252b4b40422b9e7ee4b3f9d7c8275612f158` |
| `val_tab_0302.json` | `7b977dd2d38ffb5ed3a4b0397c7183d8867cf2f6582c5afabc2b052175e3c8a9` |
| `val_tab_0303.json` | `a047dbe94e4b53210c7c8239e1c824b13c56e78650646e8daefa77bced17f9b5` |
| `val_tab_0304.json` | `56648d71cdbd1fd85a6877d48a3d3758d3fed65c091e5c40fdc2d42fa78e4990` |
| `val_tab_0305.json` | `3e7ca05adaf19659e08a50522a80f8facc5485aeef89d53fd3c5b6e11124e5af` |
| `val_tab_0306.json` | `3e7ca05adaf19659e08a50522a80f8facc5485aeef89d53fd3c5b6e11124e5af` |
| `val_tab_0321.json` | `74043554fa08fdf8bdd646c78cd4ffaf55e73f14142c3651a4f6e74c56c8253b` |
| `val_tab_0323.json` | `74043554fa08fdf8bdd646c78cd4ffaf55e73f14142c3651a4f6e74c56c8253b` |
| `val_tab_0324.json` | `0eaed9f98acb155b8f6e38b1e963516bc5fde14e2e6ff1167ab626ab363c31f8` |
| `val_tab_0327.json` | `cbee932acb1afccfc6bb0df1ed06a65f4079477354c31e27faf38d6230073182` |
| `val_tab_0328.json` | `806a511b81971e0ffdcb2e6960dd5cd4186538599dacb7b21f99c03fe36213d1` |
| `val_tab_0329.json` | `9626fb88b40589f20758be26e8035a6391020c0d4c7b721a3d31d5b5a681ba50` |
| `val_tab_0330.json` | `41eb67b2538a527a2e433be4391154372710e9d13580de381f47edb454bda32a` |
| `val_tab_0331.json` | `a61a19b82c40b99145fe509e7b48181ce8f62ae3e87b253e294a5f90d217aaaf` |
| `val_tab_0332.json` | `6dabf85c4f8e829c907fd86e816b7024c074325f40ea3feafa9ff79bb25db4f2` |
| `val_tab_0333.json` | `e95296cfe7b8a01504be34d68c473898db5f656850b2bea66e099abd35a6a732` |
| `val_tab_0335.json` | `9674cd5e2506a5aa0cf352bbdd3c15bce794678c483b0e4121faa6dbc21f7cd2` |
| `val_tab_0336.json` | `eb94234ed6073dd6fba0c60c1eda12268478f0c358d3600755f9e22639ab00f7` |
| `val_tab_0341.json` | `c39a310dc74aef3d8c3b1bbb0928f281e423d9352d13c34800c6713fae346137` |
| `val_tab_0342.json` | `a9bab933bf5fe96c3b402c8d9ff6588dd8ee0c720292798dafb59acb5986532a` |
| `val_tab_0343.json` | `aee1c4e62a1916a043fd67c79526d110b207c5e389cc803ca7dfd79825fd837a` |
| `val_tab_0344.json` | `aee1c4e62a1916a043fd67c79526d110b207c5e389cc803ca7dfd79825fd837a` |
| `val_tab_0345.json` | `883fbb19240a6be1854398f69d62299349d4f285f8e9e9a19021526d30ccc009` |
| `val_tab_0347.json` | `aee1c4e62a1916a043fd67c79526d110b207c5e389cc803ca7dfd79825fd837a` |
| `val_tab_0348.json` | `85d8ea1da9ce9899505e1a8cb2e9555b34e649f80333eaa65dcaa7162066a8c3` |
| `val_tab_0349.json` | `960bbf5b7567268c875821a8caff657ae4e94298e783eb80d19e7770b37e9984` |
| `val_tab_0350.json` | `cddcdd2e596fd95e6ebf7d2573f81c03c826ba0f70ba670807f1f2c72bafb14a` |
| `val_tab_0351.json` | `26c26bfca4e197fa890e4730473349f406ae7dfaf1fa92dc122ee86f863e8c53` |
| `val_tab_0353.json` | `05bca46d57533d04666ea560d5f8f958c761968eb026fdfd59744c01803e233a` |
| `val_tab_0354.json` | `41f35a0ab886420cc83a9d4ec8eeb199835f63867c2ebc720aab19586c6a00cb` |
| `val_tab_0355.json` | `d621c922d10c0df62677b3f64d7b94c74030c5e4ead261bd9b49ed0c4367ef4d` |
| `val_tab_0356.json` | `5ba5a4401750f99e9aedc635cf6564c0d3c6315f9c0fb678aeede540c73a8e00` |
| `val_tab_0357.json` | `c0942e0581927ea6132b3caa814246b84d20a302c2dcee660dfff41f2bb9ee11` |
| `val_tab_0358.json` | `6a9fb9f9742620c2b2e4d9b737a6b03c0964ea620418ff0c235ad8a36b2af63f` |
| `val_tab_0359.json` | `c0942e0581927ea6132b3caa814246b84d20a302c2dcee660dfff41f2bb9ee11` |
| `val_tab_0360.json` | `c0942e0581927ea6132b3caa814246b84d20a302c2dcee660dfff41f2bb9ee11` |
| `val_tab_0361.json` | `a5aeb6acd5b15a62749fa95f10646fb3dff1db6257f93a0fc39523a5f0cc4f82` |
| `val_tab_0362.json` | `939c38e4361a45892d915271037758e1e105834f3dd77b30bd57d9d2f48d5db9` |
| `val_tab_0363.json` | `99b5a171cee1ff73e02bc8adb3e03bd5c83520e4458fc9198939c4a9d168a2aa` |
| `val_tab_0365.json` | `939c38e4361a45892d915271037758e1e105834f3dd77b30bd57d9d2f48d5db9` |
| `val_tab_0366.json` | `0dda5881de12af5ade35577124ae561936afdd52ab19e80ccd303c711846a8a2` |
| `val_tab_0367.json` | `939c38e4361a45892d915271037758e1e105834f3dd77b30bd57d9d2f48d5db9` |
| `val_tab_0368.json` | `3711d9b5961b9a12a95603572ba3fc07ef21cd9c7214bf2957244168819e1709` |
| `val_tab_0369.json` | `3711d9b5961b9a12a95603572ba3fc07ef21cd9c7214bf2957244168819e1709` |
| `val_tab_0370.json` | `3711d9b5961b9a12a95603572ba3fc07ef21cd9c7214bf2957244168819e1709` |
| `val_tab_0371.json` | `944325232661c9c24a2ad4bd6f63f8f4004695fdb04e608f8fc8ce23b8f57810` |
| `val_tab_0372.json` | `c5dc716c6358100fc842bf1d95dea08cd383739b86440a8f7aef6d8929bc1352` |
| `val_tab_0373.json` | `7e26d68a50cd7863bac74b87fd1ead815fa158e3d2daf89c29eeca063ecaf979` |
| `val_tab_0374.json` | `8b448ea86b3f13d8ee896128d4443362b6cb11bd1758fd1b95497c191024d311` |
| `val_tab_0376.json` | `7f5be99227218472df646dd2eeb7ba69758bb48ec86c1f10a2af31d2fa45f8b0` |
| `val_tab_0377.json` | `7e02c26b0114ccc303786ee1f0d98ec12c853cc7f543ca038b80e5b1fe9d375f` |
| `val_tab_0379.json` | `d2784238b25ea5655214d563e3e5e4a69d9b6a568a4027d5e9bd9c928812deb3` |
| `val_tab_0380.json` | `5e40d2cae288aec0f913328c6dfd987003ac7c8218afdee1134a7d7babb23eb7` |
| `val_tab_0381.json` | `afffc06d989134e6dddd1d92996dd51e968a2d3c687daa9aaa1215416e69753d` |
| `val_tab_0382.json` | `afffc06d989134e6dddd1d92996dd51e968a2d3c687daa9aaa1215416e69753d` |
| `val_tab_0383.json` | `afffc06d989134e6dddd1d92996dd51e968a2d3c687daa9aaa1215416e69753d` |
| `val_tab_0384.json` | `fa96046fbba3117dfaf4f4d94ff7807044d5e557a209f1ccc5b3105d73918226` |
| `val_tab_0385.json` | `afffc06d989134e6dddd1d92996dd51e968a2d3c687daa9aaa1215416e69753d` |
| `val_tab_0386.json` | `21e504320b010112d5fec3d386472b70bcb5bfc29c9b6629f3372bfa0f6a1cdc` |
| `val_tab_0387.json` | `afffc06d989134e6dddd1d92996dd51e968a2d3c687daa9aaa1215416e69753d` |
| `val_tab_0388.json` | `afffc06d989134e6dddd1d92996dd51e968a2d3c687daa9aaa1215416e69753d` |
| `val_tab_0389.json` | `8ee746558539209a35a21dca0b2b61503c29c2780714875319e9af131cf21d5f` |
| `val_tab_0391.json` | `29e370ebdab88f16aa22ccef9a5d568924610169cec72296ed3cac7e411809d2` |
| `val_tab_0392.json` | `7746bd264a6f1d3cf35f1f942a02e079e54309075b1a4a448ce4bbf57ce4acee` |
| `val_tab_0393.json` | `432c29c24ce5a455b816edc1e67ee0e2a92bdbf05e1eeae7bbdf31af2a63cc5f` |
| `val_tab_0394.json` | `446f94c6af88822831d627b35659b712f440449dcf9619b16cbe1e09dba11915` |
| `val_tab_0396.json` | `3d854d22b90449c053dba293e1b60ca36d816f547b28c261153400b5a2a3879f` |
| `val_tab_0399.json` | `694f9d18a63253d14cffbe5ca8dcdee8cf7031b4cf9d198adafb209d05538569` |
| `val_tab_0400.json` | `d268be1fc6b891cc9ca700fa1f85c6791ed47c3e1dcec66a4fcf8fe85791500c` |
| `val_tab_0402.json` | `694f9d18a63253d14cffbe5ca8dcdee8cf7031b4cf9d198adafb209d05538569` |
| `val_tab_0403.json` | `31abb564da444f5aba8b890e52bff1c8e54ad44e353a9db6a7ff6dd73b93a344` |
| `val_tab_0404.json` | `694f9d18a63253d14cffbe5ca8dcdee8cf7031b4cf9d198adafb209d05538569` |
| `val_tab_0406.json` | `ca318cb5c8c87050d2622bb1d86bd1510358874b7f36748d195f9e9ca376873c` |
| `val_tab_0407.json` | `c6e74ae22787544eb16aadd904d8eef9523672ac95cbb263640d1fa936d3f93d` |
| `val_tab_0408.json` | `ad4ee8e922076987f9ba4eb6a306c420b56bd0874c1a3a324cfaa36bcde37a51` |
| `val_tab_0409.json` | `d8bd2469141f315801369a158c922adc6fac1763faded29603dc2dd05e399ae6` |
| `val_tab_0412.json` | `b26dceaa0aa589de9d3345f5d8527af09cf61ccf734058034a66ba092a7c8aa9` |
| `val_tab_0413.json` | `f86853da88ff36cd5447d2551a331d8a3dbc03c4fb7bbd398f0f4a4d5d62e5b8` |
| `val_tab_0417.json` | `4d95b247830c5cd69c679586803ab8fb9fa76d2a393235247395abf3daeafa64` |
| `val_tab_0418.json` | `7ebda5f991e26a270660de4a06cc9eea71d64c7e1ea3233697a757346b54e00e` |
| `val_tab_0419.json` | `21d90caccae8289347701043d89e56db9f7d8db918a59e0ea036ac548741f8f5` |
| `val_tab_0420.json` | `4719119f4f70071a1df12f7b48c09835b1dbcf185b660628f5e4593124729a64` |
| `val_tab_0421.json` | `94104c5aeb5314a9e1037bc38f76ce2b6e4787a2c115fa9de95d334fdea14e5e` |
| `val_tab_0422.json` | `4719119f4f70071a1df12f7b48c09835b1dbcf185b660628f5e4593124729a64` |
| `val_tab_0423.json` | `e7bc5196ef036a284c367e88f72138245a6e0419c6d08b3d2a97fe05f480de24` |
| `val_tab_0424.json` | `1489ec0758bd8ca3ce5fc831a6c1eaf52a5a0a949751a1accbd5e8eb54052aca` |
| `val_tab_0426.json` | `5f81250a1262d9a5396d028de67c6165832938d45574c8f05fa87f9d6e416544` |
| `val_tab_0427.json` | `0cc5b23d4df4c4f6a7408280934e813504ecb5dea00fa754c3ad08a254df9a10` |
| `val_tab_0429.json` | `95c1db73195310cdd18c46c6baeecd34672b0642c46568d00e81aba6b39ab887` |
| `val_tab_0430.json` | `8c2eacc2e124b173a0c8d23d15d1c19739770e74d0eea4e858795e0fc626cac6` |
| `val_tab_0431.json` | `8c2eacc2e124b173a0c8d23d15d1c19739770e74d0eea4e858795e0fc626cac6` |
| `val_tab_0432.json` | `14a679cd496549b76545a9bb03992d10659d6b6d5dc8caa2762ac54fe698692f` |
| `val_tab_0434.json` | `7c074bcb70965e073bf6f4e22691d0d2e073a74c34cb5f978face009d0ed738c` |
| `val_tab_0435.json` | `7c074bcb70965e073bf6f4e22691d0d2e073a74c34cb5f978face009d0ed738c` |
| `val_tab_0436.json` | `d78508949ae1db187e959d3f46920ed729f09e4c81de8de91ea64074ba442ba1` |
| `val_tab_0437.json` | `4c45309dd3e92c433a79596021cf76589819032b5aec4defe7489da40a70b1c4` |
| `val_tab_0438.json` | `68b87de6cc42a3bde388c321d01f793342bf288e03e9582117d81d7a007ca8bd` |
| `val_tab_0440.json` | `1a6b9bc13f0473972871577cb71b1a823c48ba070f5dab43461891d584ee5468` |
| `val_tab_0441.json` | `1a6b9bc13f0473972871577cb71b1a823c48ba070f5dab43461891d584ee5468` |
| `val_tab_0442.json` | `32300de7adb38dace7033dc879cd2fe051fc659cdcadc0974be564360e5a08ff` |
| `val_tab_0443.json` | `1a6b9bc13f0473972871577cb71b1a823c48ba070f5dab43461891d584ee5468` |
| `val_tab_0445.json` | `769bd37ea88452bed778f1074d3fa85479316689c6d0488a8a6325f7ab635144` |
| `val_tab_0446.json` | `e67e2e387300ca6c6deb87ac65e3b8121acb30fb905f4f42df0302b62ca88840` |
| `val_tab_0447.json` | `769bd37ea88452bed778f1074d3fa85479316689c6d0488a8a6325f7ab635144` |
| `val_tab_0448.json` | `3a699d5b4844455b4a18081095df782643d3ba32209619a94ab9dbdeca8ae87d` |
| `val_tab_0449.json` | `60e838daef8be03fea3384c85d6429d7c3491589b346911d445fdf433d9ed31f` |
| `val_tab_0451.json` | `5c16077a9772e4550d07a7dafb149814be6a2f14c0a71cb2cbf2810b52655a0a` |
| `val_tab_0452.json` | `3eea2ded353a1b63f98c44b31e29078c7832c92fd985c7b6e67684f7869c18f3` |
| `val_tab_0453.json` | `5c16077a9772e4550d07a7dafb149814be6a2f14c0a71cb2cbf2810b52655a0a` |
| `val_tab_0454.json` | `5c16077a9772e4550d07a7dafb149814be6a2f14c0a71cb2cbf2810b52655a0a` |
| `val_tab_0455.json` | `7fdf75a52068c6ca20d9376403acf8258d963f56e424bf4cdbf465f29524cca3` |
| `val_tab_0456.json` | `26b1de28cbfb2b97b7c3eae51c5bb505b689030bb3ba635a789dab7597917558` |
| `val_tab_0457.json` | `26b1de28cbfb2b97b7c3eae51c5bb505b689030bb3ba635a789dab7597917558` |
| `val_tab_0460.json` | `7f7e82df22b12e2e7918e832be6b4b4041f57665cac14259934c3bb121de228e` |
| `val_tab_0462.json` | `e78e70fe5bcf21f8903d3bd6d5689326ebaaf693b18d676e07d730e58f3c74a7` |
| `val_tab_0463.json` | `e78e70fe5bcf21f8903d3bd6d5689326ebaaf693b18d676e07d730e58f3c74a7` |
| `val_tab_0464.json` | `9b02489c3aef2e8cc9b138a5f58cb32ffd37ebf05fc6870cf1579792e8a95973` |
| `val_tab_0465.json` | `e78e70fe5bcf21f8903d3bd6d5689326ebaaf693b18d676e07d730e58f3c74a7` |
| `val_tab_0466.json` | `4a6a8762483a225ab9f707e71213d826085c6b84e4cfbccab06d67116bcb1099` |
| `val_tab_0468.json` | `fcea2d293c01d05ff6f96bbe306a18b856a1a4604a8f4834d7b76c7cd9445d61` |
| `val_tab_0469.json` | `fcea2d293c01d05ff6f96bbe306a18b856a1a4604a8f4834d7b76c7cd9445d61` |
| `val_tab_0472.json` | `981c4698a16b646d290b8a8bc0a2c728e1b0e41546d47fece9edb341959a5ed7` |
| `val_tab_0473.json` | `981c4698a16b646d290b8a8bc0a2c728e1b0e41546d47fece9edb341959a5ed7` |
| `val_tab_0474.json` | `981c4698a16b646d290b8a8bc0a2c728e1b0e41546d47fece9edb341959a5ed7` |
| `val_tab_0475.json` | `d185d132ab961e75e9efce19b00bfa631d82033a446770bb27b52356ca980565` |
| `val_tab_0479.json` | `cc47c67777a864da27cbd47328460a1d58e5c807631ea3164aec6c786f034cd6` |
| `val_tab_0480.json` | `4c08fbbb541d9243fa0e28452c12a80f1ba2bd1fe8c7acce1c677212d7ebb9a0` |
| `val_tab_0481.json` | `cc47c67777a864da27cbd47328460a1d58e5c807631ea3164aec6c786f034cd6` |
| `val_tab_0482.json` | `4f0f5a44f7f35df2d826af60b3ae18654cdc53de7bf61c1b57c4bd63c8f572a9` |
| `val_tab_0483.json` | `659ef241ce3e7b23f242beb12ff1d96b1ad097570fd63bbd5f8fc2538dc5ad60` |
| `val_tab_0484.json` | `c58b0dea1935ae2651f6e7657930c7dc3a7579d1020d19ad1f2b42edbf84879e` |
| `val_tab_0485.json` | `659ef241ce3e7b23f242beb12ff1d96b1ad097570fd63bbd5f8fc2538dc5ad60` |
| `val_tab_0486.json` | `659ef241ce3e7b23f242beb12ff1d96b1ad097570fd63bbd5f8fc2538dc5ad60` |
| `val_tab_0487.json` | `0fd19fbe88253028b142c29e5039d3da8f96c0d5ca8e4d090a503ae9957329b9` |
| `val_tab_0488.json` | `ff15c214ece340ac963950c389d4f7571c98f88acf387b1b46984680cb846ef3` |
| `val_tab_0489.json` | `388c053a1a6799fd35fbb2aa62b6e1ba6eec0ef8f97ac61621a9f55f712d20cb` |
| `val_tab_0490.json` | `46700d15d1e4f9ffa624228e84434fcadf47eb70577a07f522b68da3e19880b3` |
| `val_tab_0491.json` | `f28c24ad2d67f08426a4b6ef30ff612c05b23d2b7ec45f3bf6db23848ac1d493` |
| `val_tab_0492.json` | `089bbf98000f15ff1aafdc8fc245dbffece253def76fd7bc047ef0b7f78e3874` |
| `val_tab_0493.json` | `859f8435011377093df564d2e3b4dae4f02498464c42437255cf1bb3c4d274d1` |
| `val_tab_0495.json` | `8c2eacc2e124b173a0c8d23d15d1c19739770e74d0eea4e858795e0fc626cac6` |
| `val_tab_0496.json` | `8c2eacc2e124b173a0c8d23d15d1c19739770e74d0eea4e858795e0fc626cac6` |
| `val_tab_0497.json` | `26e0679418346e03d12ef705c130da2f09c7e9aadad31cc718f2487228e761ac` |
| `val_tab_0498.json` | `743d618e087a03a3f9f28f528e2c28d937a4c95d3d82b6adfc7b74ef5d129bd2` |
| `val_tab_0499.json` | `8a073c2c626e585c3aecb20d5376319a8a29998ac47cbef2e8664ead1a3b8de1` |
| `val_tab_0500.json` | `4af2e20cf99942fbe3658a38eb58ad11edc950129738e0da0d6f22b388ac3b61` |
| `val_tab_0501.json` | `8a073c2c626e585c3aecb20d5376319a8a29998ac47cbef2e8664ead1a3b8de1` |
| `val_tab_0502.json` | `010a725a27f65b3a6636dbacf29170077355f9425d03bf8787e50db7bc36872c` |
| `val_tab_0503.json` | `57698106b85a21a5c69277e74f9de3269a6f9d59ae8a7305e20c0d08ae953f02` |
| `val_tab_0504.json` | `b250558d6b77f77598bf1c45811eaab62d40afa8dd95462c3714c5d0be6edb81` |
| `val_tab_0505.json` | `7b50aa76a6375b1e59e908128c4d9fb9366726c28eed7b427ecbadf4f70444ed` |
| `val_tab_0506.json` | `b35ab4eedc71e3fd141062d6bd25f0cb59f577138a63389b6e5327e838081829` |
| `val_tab_0507.json` | `7b50aa76a6375b1e59e908128c4d9fb9366726c28eed7b427ecbadf4f70444ed` |
| `val_tab_1500.json` | `07839fffb403bc8eb9aa90d6f0968895484f5dbf53be6317b2ed6cc0c87e83d2` |
| `val_tab_1501.json` | `4b03bf80d5342664b6ebe62af1bbff364ca143a05b38083985ea692968ba19b6` |
| `val_tab_1502.json` | `240efecca66143b53552374419b11be44acf97d12c3f8a69007b3a8cba081566` |
| `val_tab_1503.json` | `64516449093874e83b03562c5fa41f2d8c39b77a804e9ec54367191bee5901b1` |
| `val_tab_1504.json` | `b94d35fff95bffab03b0784b40db0837ba531ab52c70b3bbf88ae86b69af6440` |
| `val_tab_1505.json` | `e4f891ab43eec94f2f708c36b2a8c7198cc63489261516b374c65dc2da98d5d7` |
| `val_tab_1506.json` | `2dcc03f9ea2bef3b269206977db7703a575c050075eacbcbb25ba9d638eed3c9` |
| `val_tab_1507.json` | `9152a45987fd8c9129a8e292241aa31c5604aef5b4519505ebd86bab12f1540c` |
| `val_tab_1508.json` | `4e1af053e061cf2784d1452279c96568396851aae09249dba3e81374a4d3c7bc` |
| `val_tab_1509.json` | `5c9c11b71b9ead9b14a67a90036ef9a046b67a10a0eb29d6c828428056ff7a8d` |
| `val_tab_1510.json` | `a05761eab793d9d770c25c35b07bf5dcc293bb6310fbad72ad1aa5b7c15896a5` |
| `val_tab_1511.json` | `b9cdf58fffc8590d78427b45a9c2ba6120c90802c8935439d139baa9ea08201a` |
| `val_tab_1512.json` | `e5787747fdc6e1c65de1afae982ec29ef9fb19ec912cbce7895077ab8d195c44` |
| `val_tab_1513.json` | `68e872d581a474a63d03d045bbaf029a1323ec68bad7b72fa37611ce64a606bd` |
| `val_tab_1514.json` | `e07e3d125043cb6d4ee8b70b64bcb60c6fce6412a55fd7f916c26ef40a52b1f7` |
| `val_tab_1515.json` | `76bd490977ba5062ed2759847e3822e1a9a129721cff3c4b3f866848405baaaf` |
| `val_tab_1516.json` | `0a0fcd42b8b9eb65c25247fc7667ed5e39d040cf39d9e48b814fc3a1a0dbb33f` |
| `val_tab_1517.json` | `d6b565ec26e11496f6dabe2fc31c568f1c865e21eb40360a2caa6a510c4ffd78` |
| `val_tab_1518.json` | `595f9e1c20236d299cbd9efbfbca0c8846886fc5925faa1500e287053811b29e` |
| `val_tab_1519.json` | `099391486e2d1dd83a77caa4513bba0befd438e438b0cac92a859440fcbb3ca6` |
| `val_tab_1520.json` | `8c3d226c34557a6cd6c294aad8020214cfbb5349a6ce7782e07aafcc77b477cc` |
| `val_tab_1521.json` | `c571ff23ea46a4353d3e9b4689ead5e10a87f247e2214b533ccb4ef9855562e2` |
| `val_tab_1522.json` | `2b04a250fa2e19a41fc3448c7162f1115261d3c1deba0d694d354acd256f0617` |
| `val_tab_1523.json` | `d2aadc07f09ce4443440c0ece0fad3f19d242da52fa324c5913cd7fc189e1105` |
| `val_tab_1524.json` | `5bc65ccf2dbb483e5540a854e377b85e5efa4d4558b893e70c8e665f85ea3382` |
| `val_tab_1525.json` | `936a631578e0c1380465f1a7be3c84d32f47503400c676f7861ff0ebc20d017c` |
| `val_tab_1526.json` | `d89fdf8a400278d428b728e96da4aa6d87e4bacc078664c1b6cd61c83944bd16` |
| `val_tab_1527.json` | `0e8ed101cb26588199e2effe80f807ef2b844d56a735148b0f1a761d997e435b` |
| `val_tab_1528.json` | `ae699c3e9c3266cf0368484a95eacd8796844b19b9202c278ae972c6262e915e` |
| `val_tab_1529.json` | `89f9a06724b228ade05de5f28cb96685256833087fc8023fa0dc9db9cb066590` |
| `val_tab_1530.json` | `0c998606364a3e5ac578c8574170314036b75bd1c4ac278038ae6b8aa7ba9eea` |
| `val_tab_1531.json` | `c5d57321640fb0ee07e8a98673a295f29fbe6748037ac2ac29bb87b7a6e398ea` |
| `val_tab_1532.json` | `18f5ad94f9fd40a961c70f2ed81a65b329ae587fd011884b9c4be44ed62a5679` |
| `val_tab_1533.json` | `9481ad0040b55659345b7ae898fbc9c3b1d7957c69b49452dfbff4b706ecbf67` |
| `val_tab_1534.json` | `8f3d86a06af986237b94c274e65293d7fcf380367f8b6628a65c424200456219` |
| `val_tab_1535.json` | `a990c59b4e201cb0906fc6e8c44ddba166bca6dbc9a555aad8b56071c91693a8` |
| `val_tab_1536.json` | `984281b5f6972ba053086728dce4aaebb29ff92fda98fe5e234620f504ec8703` |
| `val_tab_1537.json` | `06e3446e6c2054b4837e480fd6ce7e21867105adeb1aa1737237c3eb5b62bade` |
| `val_tab_1538.json` | `3117c6b8cc76d58c90255005cb9c22a20e1bb027dd2cd0dc0c81ec2528070bc6` |
| `val_tab_1539.json` | `c5fb5f719b321c7d2da10ae82c11f139c9016c091e6a7424c4f1acbcba9e6d77` |
| `val_tab_1540.json` | `85269b7c5b48aa5d9fc43f05d8594574414ce6e979770d2a6a534fca1da16fd7` |
| `val_tab_1542.json` | `81edf12d87f7d18bd73acd303422f65a5888408c00014e70de14d6d92cc4cf04` |
| `val_tab_1543.json` | `3228e7711b8453a2cb2de5209c9ca1ec04e600b100d3615e8a1290227b590cc9` |
| `val_tab_1544.json` | `375adc9e394ab65e4d5738d4740d49b3b1870d9cf8e747b84fe3d9953f85ab16` |
| `val_tab_1545.json` | `4468f9f29f2ed76703c943fb1ddcbf5ce3044a751464e47f3b60d2b9e714476e` |
| `val_tab_1546.json` | `0b25a16d8e17c77c0024f6d7caf524f59f69e4494c03aa70c346cd2e7f6b1579` |
| `val_tab_1547.json` | `c0d4324e0c1e362188c8279bee67e7bbbffaa50868ffb00910bb493299c50b09` |
| `val_tab_1548.json` | `ee89bbc24d7a21e92044851e5524e55ae04ac952a02bbbd8826b4a3dea92433f` |
| `val_tab_1549.json` | `e43d3eadd6d081a3b23f3ae12534586969f272e650a390947e5351ed5075d818` |
| `val_tab_1550.json` | `717b473b4d215d0c909092393b6c50477d6c1052764663a072a768f3fa602819` |
| `val_tab_1551.json` | `b892a41a9c121a45ad833817eca672bcc6e0e937481d85646dffad92ca573f21` |
| `val_tab_1552.json` | `73897ca102e77d577b5943eca5585e706f1d657eadd7f13540b7ad61dbc4a133` |
| `val_tab_1553.json` | `1caf6c7b24ae47cb27901b252e4e2437d37bb27847967d8c7641fc2fb56d5109` |
| `val_tab_1554.json` | `0f75a928ed1db4f334782d1dbc2109268db0c85acb5b907e1d1a164ee056ebac` |
| `val_tab_1555.json` | `fac9dd4f3dbde5f8d2f9aa9ffdce6e3df55aab534bf300f2a8260896266bcc92` |
| `val_tab_1556.json` | `16013c47e3637f2514de39836d10a6106e372992753a6cca39b75761cf2cf1cb` |
| `val_tab_1557.json` | `f29959564dfb278c2d355048e145568021c3b5507a83d32c0d7326c246747b2b` |
| `val_tab_1558.json` | `2d5b65aec78a53e59d3773b1b9db28e354a02623089680e2a351be4c7ad5d08c` |
| `val_tab_1559.json` | `86664d034a98bd1758990f7c2922faa0053ed00e8b9b32020e7db71cb2dca9c8` |
| `val_tab_1560.json` | `1a7dda4f4bbb10f71bb4ff52719c19898b410166fb04ccb7f1cc422b6ea2c868` |
| `val_tab_1561.json` | `64ea1ca577f743a06ac5e5322a497a4b936062527cda9aa1176f2c5cc3178b39` |
| `val_tab_1562.json` | `932792a0428488a2156e9ed8e8a3baa016d29bb5a37384250a2c1665832f0305` |
| `val_tab_1563.json` | `6ba04803e34c79ddfbc6c26e27beb759096cbb6450e95af4dce7e1fd0fe90313` |
| `val_tab_1564.json` | `19c1ca98bfbaafd97b8f4dcb69042c784fb34b309d40f08da0f5b2388f8c4e5c` |
| `val_tab_1565.json` | `ebe4e7d812f282a6981f74dffa043ee8480388343fa9176e870dea5122be2ad4` |
| `val_tab_1566.json` | `ab623cae176bcf8c3231804ecbf4df51162e8f403e8b9d3b8ed42cf1ad3b7950` |
| `val_tab_1567.json` | `82b2d4070881a5a733342da8f764fdef8c507d94bfddb1c3b8aa2f8cd405bd4d` |
| `val_tab_1568.json` | `1ac7db679036fa54bbb1078f1cd9075d4a1cc5a53642a5bea600eeec6e3f5e49` |
| `val_tab_1569.json` | `f163b96311b600be59ede8c95db4dbb1a5a15926f8a474a60397d7d99205197b` |
| `val_tab_1570.json` | `f914fc997ec57051cf49423b55f74f93cadbae13bc9b0500424e250c4ef25dc8` |
| `val_tab_1571.json` | `f2a7fee7077ebe9189b488b4a9235664a9f6469030b05260bf1fb8c093bd3005` |
| `val_tab_1572.json` | `e5b018f3108ce690e5b366ce4f0c9d0adfeac2b84f41ec7ccc8013b7a8d4d9a4` |
| `val_tab_1573.json` | `59d7dfe385da74484db879a6428aeb90bef28d232359d877ca1c4b9bd4bd0ac3` |
| `val_tab_1574.json` | `2372e71a3afadfc88346fe6855e3c275c55133476cdb3e7127b4a71f4dd16a5f` |
| `val_tab_1575.json` | `1083f53525ee52a9e0873e1793ec286f622776b071b4356df3934165c644eb01` |
| `val_tab_1576.json` | `32c5d89c04d8b125fdf96d22f7661b5a921222f867958d993b96b1c1200db6c6` |
| `val_tab_1577.json` | `e29f53ecb9f4a8c0f09657a4eab73afce13bffa41932a848ad356c3b89490d35` |
| `val_tab_1578.json` | `80dd6e927f51e5646f1feed66c784af0a6a63714bb072c0482bb673284bfb042` |
| `val_tab_1579.json` | `e34356206c9c5d9142ecd17d8a4d64f8880ded2b887ed02d829183976014f92b` |
| `val_tab_1580.json` | `c3818b830b3ed36e770a84dadf374926806b090d4423ef7e0636ed34c53ff24c` |
| `val_tab_1581.json` | `da10b160b18de78e8bc48b6ca1bcff0cc932975c98054c93e596734c3d8890ef` |
| `val_tab_1582.json` | `c9345f1aef2416c22d225a35a9f7ca872aa89aeac56c4ff420ab39ebf846765e` |
| `val_tab_1583.json` | `bdf00a6f16c2c0b31b4fdeb8ab11f577fd9ce7dd54c8448fabd76b1ae8268b86` |
| `val_tab_1584.json` | `bb2ccae85b98c4d4526d798cb437dec8d1003e3cf80ac0c9ca13c24a0be4eb17` |
| `val_tab_1585.json` | `a8cb23338008b5eb4cc18f8c4c7f33bf314b8d80cb245f661a9a70aff6eb3e52` |
| `val_tab_1586.json` | `4422f8286512f8d0c60b1f4cb40f9aad2ed6e1be0369ff47db10b05a09237e28` |
| `val_tab_1587.json` | `4e787be4b3fc5c8d946364e96778dc87c191c3fc7ea50c8b10d6a79e2f7c6bd7` |
| `val_tab_1588.json` | `de4b51119c079cf0291963929e09d6fafd188bf318dfa2824370438df6b6c4aa` |
| `val_tab_1589.json` | `530a3b1903d7bb5d3f6ad700622652cede08092fbf61463e4e13f5950814e158` |
| `val_tab_1590.json` | `f42376d912ae6241ff032924e4ce2e285b3ae6636a05ade4b69c3fcb749507fc` |
| `val_tab_1591.json` | `904d69adbb28c7073946f8758875e21c717e18829be7364d256cca817ff594a8` |
| `val_tab_1592.json` | `2b1258bd70f571e8c0a9dd97b746283d8539718d58a93908a9e9986a6cbab19e` |
| `val_tab_1593.json` | `c53f95c56410416506ae8d6283d5f4b4d0bf734a2e4e76e2878780427a5ae8cb` |
| `val_tab_1594.json` | `66598b086e2dcc42d19e3666a32f0b728fe85d39754ac0dff64a4fcb223d510c` |
| `val_tab_1595.json` | `0a899279f5d93222f02eed89ae7239b829cd9469859c497c101f3e3014f7e05a` |
| `val_tab_1596.json` | `d172be64b4a470a032341bf0de646ea1aaf16b542dccfdfec67a40c11a32748e` |
| `val_tab_1597.json` | `9d350c862765f365e3b4ced995a273bc6237f26081fe45ca37d1c4416476a92e` |
| `val_tab_1598.json` | `d68da2806f208a13dfcdb78a6f89c7e39157514626dc8a214506c1c3d7568296` |
| `val_tab_1599.json` | `4950a4e0ba2d440d27ea831d82aa494cbd13f568a723653cfc64951aaedf2800` |
| `val_tab_1600.json` | `e0fa438c0e220c4bc8abc0b537f01c1b8de1e8b503967a55684a7f7aa647e26e` |
| `val_tab_1603.json` | `62fff3fde461f9a5dde98e78470ce183f42708868058aeeb91af623e6ede56b1` |
| `val_tab_1604.json` | `2e8f0cdb661d9112962828ebe75f531dfd8614cc5e18e74423999f791125fb6b` |
| `val_tab_1605.json` | `ea73f4dba8411e638f72eebc966ad73ff9c509f2d0f2eeca24ba3bf474f33ca8` |
| `val_tab_1606.json` | `8704669ffd7b96a356cfa5cf5aa6b335936a6e1ae51361a0eba220abd65338bf` |
| `val_tab_1607.json` | `5f11a80d8246ef9fac354d2f641861d7ef1b3a2cd804129ae5e62fbc3e09fc72` |
| `val_tab_1608.json` | `8c711dda3a5f8dbbf091252b78829141ff22423b63a2d9b8405cb99426d3123e` |

</details>

