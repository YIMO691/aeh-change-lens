using System;
using System.Collections;

namespace UnityEngine
{
    public class Object { }
    public class ScriptableObject : Object { }
    public class Component : Object
    {
        protected T GetComponent<T>() where T : Component => default;
        protected Component GetComponent(Type type) => default;
    }
    public class Behaviour : Component { }
    public class Coroutine : Object { }
    public class MonoBehaviour : Behaviour
    {
        protected void SendMessage(string name, object value, SendMessageOptions options) { }
        protected Coroutine StartCoroutine(IEnumerator routine) => default;
        protected Coroutine StartCoroutine(string methodName) => default;
    }
    public sealed class SerializeField : Attribute { }
    public static class Debug { public static void Log(object value) { } }
    public enum SendMessageOptions { RequireReceiver, DontRequireReceiver }
}

namespace UnityEngine.Events
{
    public abstract class UnityEventBase { }
    public class UnityEvent<T> : UnityEventBase { public void Invoke(T value) { } }
}
