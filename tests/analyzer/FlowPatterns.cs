using System;
using System.Collections;
using System.Threading.Tasks;
using UnityEngine;

namespace ChangeLens.Fixture
{
    public sealed class OtherComponent : MonoBehaviour { }

    public sealed class FlowController : MonoBehaviour
    {
        private event Action Tick;
        private Action callback;

        private void OnEnable()
        {
            Tick += HandleTick;
            callback += HandleTick;
        }

        private void Update()
        {
            Tick?.Invoke();
            callback?.Invoke();
            StartCoroutine(Run());
            StartCoroutine("LegacyFlow");
            GetComponent<OtherComponent>();
        }

        private IEnumerator Run()
        {
            yield return null;
        }

        private async Task Load()
        {
            await Task.Delay(1);
        }

        private void LookupByType()
        {
            GetComponent(typeof(OtherComponent));
        }

        private void HandleTick() { }
    }
}
